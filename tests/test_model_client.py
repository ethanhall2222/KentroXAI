from __future__ import annotations

import json
from pathlib import Path

from trusted_ai_toolkit.config import load_config
from trusted_ai_toolkit.model_client import embed_texts, invoke_model, resolve_embedding_model_name


class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_invoke_model_routes_to_ollama_generate(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project_name: demo
adapters:
  provider: ollama
  endpoint: http://localhost:11434
  model: qwen2.5-coder:3b
  request_format: auto
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)

    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout: int):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeHttpResponse({"response": "Synthetic Ollama reply"})

    monkeypatch.setattr("trusted_ai_toolkit.model_client.request.urlopen", _fake_urlopen)

    result = invoke_model("hello", cfg)

    assert result.route == "ollama_generate"
    assert result.request_url == "http://localhost:11434/api/generate"
    assert result.output_text == "Synthetic Ollama reply"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["body"] == {"model": "qwen2.5-coder:3b", "prompt": "hello", "stream": False}


def test_invoke_model_routes_to_chat_completions(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project_name: demo
adapters:
  provider: openai_compatible
  endpoint: http://localhost:9999/v1
  model: demo-model
  request_format: chat_completions
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout: int):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeHttpResponse({"choices": [{"message": {"content": "Synthetic chat reply"}}]})

    monkeypatch.setattr("trusted_ai_toolkit.model_client.request.urlopen", _fake_urlopen)

    result = invoke_model("hello", cfg)

    assert result.route == "chat_completions"
    assert result.request_url == "http://localhost:9999/v1/chat/completions"
    assert result.output_text == "Synthetic chat reply"
    assert captured["body"] == {
        "model": "demo-model",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_embed_texts_routes_to_ollama_embed(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project_name: demo
adapters:
  provider: ollama
  endpoint: http://localhost:11434
  model: qwen2.5-coder:3b
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)

    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout: int):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeHttpResponse({"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    monkeypatch.setattr("trusted_ai_toolkit.model_client.request.urlopen", _fake_urlopen)

    result = embed_texts(["hello", "world"], cfg, model_name="nomic-embed-text")

    assert result.request_url == "http://localhost:11434/api/embed"
    assert result.embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["body"] == {"model": "nomic-embed-text", "input": ["hello", "world"]}


def test_embed_texts_parses_openai_data_response(tmp_path: Path, monkeypatch) -> None:
    """Regression: the OpenAI embeddings API returns vectors under
    payload["data"][*]["embedding"], not the Ollama-style payload["embeddings"]
    list-of-lists.  _extract_embeddings used to know only about the Ollama
    shape and a single-vector shorthand, so every embed_texts call against
    OpenAI raised "embedding response did not contain usable vectors".

    This test pins the OpenAI shape end-to-end through embed_texts.
    """
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project_name: demo
adapters:
  provider: openai_compatible
  endpoint: https://api.openai.com/v1
  model: gpt-4.1-mini
  api_key_env: OPENAI_API_KEY
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout: int):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeHttpResponse(
            {
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]},
                    {"object": "embedding", "index": 1, "embedding": [0.4, 0.5, 0.6]},
                ],
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            }
        )

    monkeypatch.setattr("trusted_ai_toolkit.model_client.request.urlopen", _fake_urlopen)

    result = embed_texts(["hello", "world"], cfg)

    assert result.request_url == "https://api.openai.com/v1/embeddings"
    assert result.embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured["body"] == {"model": "text-embedding-3-small", "input": ["hello", "world"]}


def test_resolve_embedding_model_name_defaults_for_openai_compatible(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project_name: demo
adapters:
  provider: openai_compatible
  endpoint: https://api.openai.com/v1
  model: gpt-4.1-mini
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)

    assert resolve_embedding_model_name(cfg) == "text-embedding-3-small"
