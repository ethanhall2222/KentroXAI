"""Model invocation helpers for live simulation runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from trusted_ai_toolkit.schemas import ToolkitConfig


class ModelInvocationError(RuntimeError):
    """Raised when a configured model provider cannot be invoked."""


@dataclass(slots=True)
class ModelInvocationResult:
    """Normalized model invocation result used by the toolkit pipeline."""

    provider: str
    model: str
    route: str
    output_text: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    request_url: str


@dataclass(slots=True)
class EmbeddingInvocationResult:
    """Normalized embedding invocation result used by empirical metrics."""

    provider: str
    model: str
    route: str
    embeddings: list[list[float]]
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    request_url: str


def _resolve_endpoint(config: ToolkitConfig) -> str:
    if config.adapters.provider == "ollama":
        return (config.adapters.endpoint or "http://localhost:11434").rstrip("/")

    endpoint = config.adapters.endpoint
    if not endpoint:
        raise ModelInvocationError("adapters.endpoint must be configured for live simulation runs")
    return endpoint.rstrip("/")


def _resolve_model_name(config: ToolkitConfig) -> str:
    if config.adapters.model:
        return config.adapters.model

    if config.adapters.provider == "ollama":
        return "qwen2.5-coder:3b"

    model_name = config.system.model_name if config.system else None
    if not model_name:
        raise ModelInvocationError("adapters.model or system.model_name must be configured for live simulation runs")
    return model_name


def resolve_embedding_model_name(config: ToolkitConfig) -> str:
    """Resolve the embedding model name for the configured provider.

    Generation and embedding models should be configured separately. Reusing a
    chat model for embeddings is both expensive and, for OpenAI, often
    incorrect. This helper keeps the provider-specific default in one place.
    """

    if config.adapters.embedding_model:
        return config.adapters.embedding_model
    if config.adapters.provider == "ollama":
        return "nomic-embed-text"
    return "text-embedding-3-small"


def _resolve_route(config: ToolkitConfig, endpoint: str) -> tuple[str, str]:
    route = config.adapters.request_format
    provider = config.adapters.provider

    if route == "auto":
        if provider == "ollama":
            route = "ollama_generate"
        elif endpoint.endswith("/chat/completions"):
            route = "chat_completions"
        elif endpoint.endswith("/responses"):
            route = "responses"
        else:
            route = "responses"

    if route == "responses":
        url = endpoint if endpoint.endswith("/responses") else f"{endpoint}/responses"
    elif route == "chat_completions":
        url = endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
    elif route == "ollama_generate":
        url = endpoint if endpoint.endswith("/api/generate") else f"{endpoint}/api/generate"
    else:
        raise ModelInvocationError(f"unsupported request format: {route}")

    return route, url


def _authorization_headers(config: ToolkitConfig) -> dict[str, str]:
    if config.adapters.provider == "ollama":
        return {}

    api_key = os.getenv(config.adapters.api_key_env)
    if not api_key:
        raise ModelInvocationError(
            f"environment variable {config.adapters.api_key_env} must be set for live simulation runs"
        )
    return {"Authorization": f"Bearer {api_key}"}


def _build_request_payload(
    prompt: str,
    model_name: str,
    route: str,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if route == "responses":
        payload: dict[str, Any] = {"model": model_name, "input": prompt}
    elif route == "chat_completions":
        payload = {
            "model": model_name,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }
    elif route == "ollama_generate":
        payload = {"model": model_name, "prompt": prompt, "stream": False}
    else:
        raise ModelInvocationError(f"unsupported request format: {route}")

    # Merge caller-supplied fields (temperature, seed, top_p, options, etc.)
    # without clobbering the structural keys the route extraction relies on.
    if extra_payload:
        for key, value in extra_payload.items():
            if key in {"model", "input", "messages", "prompt"}:
                continue
            payload[key] = value
    return payload


def _extract_responses_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)
        if chunks:
            return "\n".join(chunks).strip()

    raise ModelInvocationError("provider response did not contain a usable text output")


def _extract_chat_completions_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelInvocationError("chat completions response did not include choices")

    message = choices[0].get("message", {})
    if not isinstance(message, dict):
        raise ModelInvocationError("chat completions response did not include a valid message")

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    chunks.append(text)
        if chunks:
            return "\n".join(chunks).strip()

    raise ModelInvocationError("chat completions response did not contain usable content")


def _extract_ollama_text(payload: dict[str, Any]) -> str:
    response_text = payload.get("response")
    if isinstance(response_text, str) and response_text.strip():
        return response_text.strip()
    raise ModelInvocationError("ollama response did not contain usable content")


def _extract_output_text(payload: dict[str, Any], route: str) -> str:
    if route == "responses":
        return _extract_responses_text(payload)
    if route == "chat_completions":
        return _extract_chat_completions_text(payload)
    if route == "ollama_generate":
        return _extract_ollama_text(payload)
    raise ModelInvocationError(f"unsupported request format: {route}")


def _extract_embeddings(payload: dict[str, Any]) -> list[list[float]]:
    # Ollama / batch shorthand:  payload["embeddings"] = [[...], [...], ...]
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list) and embeddings and all(isinstance(item, list) for item in embeddings):
        return embeddings

    # OpenAI / Azure-OpenAI shape:
    #   payload["data"] = [{"embedding": [...], "index": 0, "object": "embedding"}, ...]
    # The list is one element per input text and is returned in input order;
    # we rely on that ordering rather than the optional "index" field so we
    # don't depend on a key the API may rename.
    data = payload.get("data")
    if isinstance(data, list) and data:
        extracted: list[list[float]] = []
        for item in data:
            if not isinstance(item, dict):
                extracted = []
                break
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector or not all(
                isinstance(component, (int, float)) for component in vector
            ):
                extracted = []
                break
            extracted.append([float(component) for component in vector])
        if extracted and len(extracted) == len(data):
            return extracted

    # Single-input shorthand (some providers): payload["embedding"] = [...]
    single = payload.get("embedding")
    if isinstance(single, list) and single and all(isinstance(item, (int, float)) for item in single):
        return [[float(item) for item in single]]

    raise ModelInvocationError("embedding response did not contain usable vectors")


def invoke_model(
    prompt: str,
    config: ToolkitConfig,
    extra_payload: dict[str, Any] | None = None,
) -> ModelInvocationResult:
    """Invoke the configured live model provider and normalize the response.

    Parameters
    ----------
    prompt:
        The user-facing prompt string.  For chat routes it becomes the single
        user message; for ``responses`` and ``ollama_generate`` routes it is
        passed through directly.
    config:
        Toolkit configuration (only the ``adapters`` section is consulted).
    extra_payload:
        Optional dict merged into the JSON body of the outgoing request after
        the structural keys are built.  Use this to inject deterministic-mode
        controls (``temperature``, ``seed``, provider ``options``, etc.)
        without forking the request builder per call site.  Keys that would
        clobber the structural fields (``model``, ``input``, ``messages``,
        ``prompt``) are silently ignored.
    """

    provider = config.adapters.provider
    if provider not in {"openai_compatible", "azure_openai", "ollama"}:
        raise ModelInvocationError(f"live simulation is not supported for provider: {provider}")

    endpoint = _resolve_endpoint(config)
    model_name = _resolve_model_name(config)
    # Normalize the configured provider into one concrete HTTP route so the
    # rest of the pipeline can stay provider-agnostic.
    route, url = _resolve_route(config, endpoint)
    request_payload = _build_request_payload(prompt, model_name, route, extra_payload)

    headers = {
        "Content-Type": "application/json",
        **_authorization_headers(config),
    }
    req = request.Request(
        url,
        data=json.dumps(request_payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=config.adapters.timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ModelInvocationError(f"provider returned HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise ModelInvocationError(f"provider request failed: {exc.reason}") from exc

    try:
        response_payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ModelInvocationError("provider response was not valid JSON") from exc
    if not isinstance(response_payload, dict):
        raise ModelInvocationError("provider response must be a JSON object")

    return ModelInvocationResult(
        provider=provider,
        model=model_name,
        route=route,
        output_text=_extract_output_text(response_payload, route),
        request_payload=request_payload,
        response_payload=response_payload,
        request_url=url,
    )


def embed_texts(texts: list[str], config: ToolkitConfig, model_name: str | None = None) -> EmbeddingInvocationResult:
    """Invoke the configured provider for embeddings if supported."""

    provider = config.adapters.provider
    if provider not in {"ollama", "openai_compatible", "azure_openai"}:
        raise ModelInvocationError(f"embeddings are not supported for provider: {provider}")

    endpoint = _resolve_endpoint(config)
    # Embedding model selection is kept separate from generation model
    # selection so OpenAI and Ollama runs can use the correct model family for
    # semantic scoring.
    resolved_model = model_name or resolve_embedding_model_name(config)
    if provider == "ollama":
        url = endpoint if endpoint.endswith("/api/embed") else f"{endpoint}/api/embed"
        payload = {"model": resolved_model, "input": texts}
    else:
        url = endpoint if endpoint.endswith("/embeddings") else f"{endpoint}/embeddings"
        payload = {"model": resolved_model, "input": texts}

    headers = {
        "Content-Type": "application/json",
        **_authorization_headers(config),
    }
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=config.adapters.timeout_seconds) as response:
            raw_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ModelInvocationError(f"provider returned HTTP {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise ModelInvocationError(f"provider request failed: {exc.reason}") from exc

    try:
        response_payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ModelInvocationError("embedding response was not valid JSON") from exc
    if not isinstance(response_payload, dict):
        raise ModelInvocationError("embedding response must be a JSON object")

    return EmbeddingInvocationResult(
        provider=provider,
        model=resolved_model,
        route="embeddings",
        embeddings=_extract_embeddings(response_payload),
        request_payload=payload,
        response_payload=response_payload,
        request_url=url,
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM rationalization helpers (Tim2 — Option A & B)
# ─────────────────────────────────────────────────────────────────────────────
#
# These wrappers add two governance-relevant capabilities on top of the bare
# invoke_model HTTP path:
#
#   1. Deterministic-mode injection.  For LLM-as-judge metrics and LLM
#      narrative generation, reproducibility is non-negotiable: the same
#      input must produce the same output across runs, otherwise scorecards
#      become unauditable.  ``_deterministic_extra_payload`` builds the
#      provider-specific dict that asks for temperature=0 and a fixed seed.
#
#   2. Stub-safe invocation.  ``invoke_model_safely`` wraps invoke_model and
#      returns None when the provider is "stub", the adapter raises, or the
#      network call fails.  Callers can then fall back to a deterministic
#      result (e.g., advisory metric reports value=None and data_basis=
#      "llm_unavailable") without crashing the pipeline.

_DETERMINISTIC_SEED: int = 42


def _deterministic_extra_payload(provider: str) -> dict[str, Any]:
    """Provider-specific JSON fields requesting deterministic generation."""

    if provider == "ollama":
        # Ollama nests sampling controls under "options".
        return {"options": {"temperature": 0, "seed": _DETERMINISTIC_SEED, "num_predict": 256}}
    # OpenAI-compatible providers accept top-level temperature/seed.
    return {"temperature": 0, "seed": _DETERMINISTIC_SEED, "max_tokens": 256}


def invoke_model_safely(
    prompt: str,
    config: ToolkitConfig,
    deterministic: bool = True,
) -> ModelInvocationResult | None:
    """Invoke the configured provider, returning None on any failure path.

    Used by LLM-judge metrics and the narrative generator.  The caller is
    expected to gracefully degrade when None is returned: stay on the
    deterministic baseline, mark the metric as ``llm_unavailable``, or skip
    the narrative section entirely.

    Returns
    -------
    ModelInvocationResult on success, or None when:
        * the configured provider is "stub" (no live adapter)
        * the adapter raises ModelInvocationError (missing key, bad endpoint)
        * the network call fails for any reason
    """

    provider = config.adapters.provider
    if provider == "stub":
        return None

    extra = _deterministic_extra_payload(provider) if deterministic else None
    try:
        return invoke_model(prompt, config, extra_payload=extra)
    except ModelInvocationError:
        return None
    except Exception:
        # Last-ditch defense: a malformed provider response or a urllib
        # internal error must not crash the governance pipeline.  The caller
        # falls back to the deterministic baseline.
        return None
