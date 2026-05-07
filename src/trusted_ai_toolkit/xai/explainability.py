"""
Explainability engines for RAG-based language model governance artifacts.

This module provides three complementary post-hoc XAI methods designed for
black-box LLM outputs.  They operate on already-generated text stored in
``prompt_run.json`` — no second model invocation is required.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
METHODS IMPLEMENTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Context Attribution
   Ranks each retrieved context chunk by its lexical influence on the model
   output.  Uses TF-IDF cosine similarity to score each chunk individually,
   then computes a leave-one-out (LOO) delta to measure how much removing
   that chunk would reduce overall source coverage in the response.

   Governance use: "Which retrieved sources actually drove this answer?"

2. LIME-style Leave-One-Out (LOO) Prompt Attribution
   Inspired by LIME (Ribeiro et al., 2016).  The prompt is split into
   sentence-level segments.  Each segment is removed in turn; the resulting
   drop in TF-IDF cosine similarity between the model output and the
   remaining prompt is recorded as the segment's attribution score.
   Higher scores indicate higher influence on the output.

   Governance use: "Which parts of the user query shaped the answer?"
   Reference: Ribeiro et al. (2016) — https://arxiv.org/abs/1602.04938

3. SHAP-style Monte Carlo Shapley Values
   Implements the random permutation approximation to Shapley values
   (Lundberg & Lee, 2017).  Each sentence's Shapley value is its average
   marginal contribution to the TF-IDF similarity score across K randomly
   sampled orderings of all sentences.  Shapley values satisfy efficiency,
   symmetry, and the dummy property — the only mathematically fair credit
   assignment satisfying all three axioms simultaneously.

   For short prompts (≤ 8 sentences) exact values are computed over all
   2^N coalitions.  Longer prompts use Monte Carlo sampling (K = 300).

   Governance use: "What is each segment's fair share of credit for the
   model output, averaged over all possible coalition orderings?"
   Reference: Lundberg & Lee (2017) — https://arxiv.org/abs/1705.07874
              Shapley, L.S. (1953). Contributions to the Theory of Games.

4. Counterfactual Summary
   Synthesises narrative counterfactual statements from existing evaluation
   metrics and lineage data already computed by the toolkit pipeline.  Each
   statement answers "what would happen if X were absent?", giving governance
   reviewers concrete impact estimates without requiring new model calls.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DESIGN CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Zero external dependencies — pure Python stdlib only (math, re, random).
  Consistent with the toolkit's AIF360-compatible dependency-free philosophy.
- Deterministic: seeded RNG ensures evidence packs are reproducible.
- Graceful on empty/missing inputs: returns zeroed-out payloads, never raises.
- All scores are rounded to 4 decimal places for governance readability.
- TF-IDF tokenisation and stopwords are kept consistent with
  ``trusted_ai_toolkit.eval.metrics`` so scores are cross-comparable.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from random import Random
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Module-level constants
# ─────────────────────────────────────────────────────────────────────────────

# Minimum number of meaningful (non-stopword) tokens a sentence must contain
# to be included in the attribution analysis.  Shorter fragments — headers,
# single-word bullets, punctuation-only lines — add noise without contributing
# signal to the TF-IDF scoring.
_MIN_SENTENCE_TOKENS: int = 4

# Threshold for switching from exact Shapley computation (exponential in N)
# to Monte Carlo approximation.  At N = 8 we evaluate 2^8 = 256 subsets,
# which takes a few milliseconds.  Above this threshold the exact approach
# becomes impractical within a synchronous governance pipeline.
_SHAPLEY_EXACT_MAX_SEGMENTS: int = 8

# Number of Monte Carlo permutations for Shapley estimation when the prompt
# has more than _SHAPLEY_EXACT_MAX_SEGMENTS sentences.  Higher values reduce
# variance but increase wall-clock time.  300 samples gives a standard error
# of roughly σ/√300 ≈ 0.06σ — adequate for governance score cards.
_SHAPLEY_MC_SAMPLES: int = 300

# Number of LOO bootstrap resampling iterations used to estimate confidence
# intervals on LIME-style attribution scores.  200 samples match the bootstrap
# budget used elsewhere in trusted_ai_toolkit.eval.metrics.
_LOO_BOOTSTRAP_SAMPLES: int = 200

# Deterministic seed for all RNG operations so every run with the same prompt
# produces identical XAI artefacts.  Change this to introduce intentional
# variance for sensitivity testing.
_RNG_SEED: int = 42

# Shared stopword list — kept identical to the set in
# trusted_ai_toolkit.eval.metrics so token sets are cross-comparable when
# governance reviewers inspect both XAI scores and eval metric details.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "their",
    "this", "to", "we", "with",
})

# Regex matching one alphanumeric token (same pattern as eval/metrics).
_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"[a-z0-9]+")

# Regex for sentence-boundary detection.  Splits on sentence-ending
# punctuation (. ! ?) followed by one or more whitespace characters and an
# uppercase letter, a quote, or a digit beginning the next sentence.
# Lookbehind asserts the punctuation character; lookahead asserts the opening
# of the next sentence without consuming it, so the first word is preserved.
_SENTENCE_BOUNDARY: re.Pattern[str] = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z\"\d])'
)


# ─────────────────────────────────────────────────────────────────────────────
# Internal text-processing helpers
# ─────────────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """
    Tokenise ``text`` into lowercase alphanumeric tokens, removing stopwords.

    The tokenisation strategy is intentionally identical to the one used in
    ``trusted_ai_toolkit.eval.metrics`` so that XAI attribution scores are
    directly comparable with TF-IDF-based evaluation metrics (e.g.
    ``output_support_tfidf``, ``context_relevance_tfidf``).

    Args:
        text: Raw input string of any length.

    Returns:
        A list of lowercase alphanumeric tokens with stopwords removed.
        Returns an empty list for empty or whitespace-only input.
    """
    return [
        token
        for token in _TOKEN_PATTERN.findall(text.lower())
        if token not in _STOPWORDS
    ]


def _split_sentences(text: str) -> list[str]:
    """
    Split ``text`` into attribution-ready sentence segments.

    Strategy:
      1. Split on double-newlines (paragraph breaks) first.
      2. Within each paragraph, apply sentence-boundary regex to detect
         terminal punctuation followed by an uppercase letter.
      3. Filter out fragments with fewer than ``_MIN_SENTENCE_TOKENS``
         meaningful tokens so headers, bullets, and short clauses do not
         distort attribution scores.

    This avoids false splits on common abbreviations (e.g. "Dr. Smith",
    "i.e. context") because the boundary regex requires the next word to
    begin with an uppercase letter — a heuristic that works well for the
    structured English prose typical of governance prompts.

    Args:
        text: Raw prompt or passage to split.

    Returns:
        A list of non-empty sentence strings, each with at least
        ``_MIN_SENTENCE_TOKENS`` meaningful tokens.  Returns a single-element
        list containing the original text if no sentence boundaries are found.
    """
    if not text or not text.strip():
        return []

    # Step 1 — coarse split on paragraph breaks (double newlines).
    paragraphs: list[str] = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Step 2 — fine split on sentence boundaries within each paragraph.
    raw_sentences: list[str] = []
    for para in paragraphs:
        parts = _SENTENCE_BOUNDARY.split(para)
        raw_sentences.extend(p.strip() for p in parts if p.strip())

    # Step 3 — filter fragments that are too short to carry attribution signal.
    sentences = [s for s in raw_sentences if len(_tokenize(s)) >= _MIN_SENTENCE_TOKENS]

    # Fallback: if filtering removed everything, return the original text as-is
    # so the caller always receives at least one segment to analyse.
    return sentences if sentences else [text.strip()]


def _tfidf_vectors(texts: list[str]) -> list[dict[str, float]]:
    """
    Compute TF-IDF weight vectors for a list of texts.

    Each text is represented as a sparse dictionary mapping token → TF-IDF
    weight.  The IDF formula uses Laplace (+1) smoothing to avoid division
    by zero and to down-weight tokens that appear in every document.

    Algorithm:
        TF(t, d)  = count(t in d) / |d|
        IDF(t)    = log((1 + N) / (1 + df(t))) + 1    [sklearn-style smooth IDF]
        weight(t) = TF(t, d) * IDF(t)

    This implementation is intentionally identical to the one in
    ``trusted_ai_toolkit.eval.metrics`` to ensure score consistency.

    Args:
        texts: A list of text strings forming the comparison corpus.

    Returns:
        A list of sparse TF-IDF vectors (one per input text) as dicts.
        An empty list is returned if ``texts`` is empty.
    """
    tokenized = [_tokenize(text) for text in texts]
    doc_count = len(tokenized)
    if doc_count == 0:
        return []

    # Compute document frequency: how many documents contain each token.
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))

    vectors: list[dict[str, float]] = []
    for tokens in tokenized:
        counts: Counter[str] = Counter(tokens)
        total = sum(counts.values())
        vector: dict[str, float] = {}
        for token, count in counts.items():
            tf = count / total if total else 0.0
            # Laplace-smoothed IDF (consistent with sklearn's default).
            idf = math.log((1 + doc_count) / (1 + document_frequency[token])) + 1.0
            vector[token] = tf * idf
        vectors.append(vector)

    return vectors


def _sparse_cosine(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """
    Compute cosine similarity between two sparse TF-IDF weight vectors.

    Only iterates over tokens in ``vec_a`` for the dot product (sparse
    multiplication).  Both norms are computed over the full vector to ensure
    mathematical correctness regardless of which vector is larger.

    Args:
        vec_a: First TF-IDF weight vector as a token → weight dict.
        vec_b: Second TF-IDF weight vector as a token → weight dict.

    Returns:
        Cosine similarity in [0.0, 1.0].  Returns 0.0 if either vector is
        empty or has zero norm.
    """
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(weight * vec_b.get(token, 0.0) for token, weight in vec_a.items())
    norm_a = math.sqrt(sum(w * w for w in vec_a.values()))
    norm_b = math.sqrt(sum(w * w for w in vec_b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _tfidf_cosine_sim(text_a: str, text_b: str) -> float:
    """
    Convenience wrapper: compute TF-IDF cosine similarity between two strings.

    Treats ``text_a`` and ``text_b`` as a two-document corpus so IDF weights
    are computed relative to each other.  This is the same formulation used
    in the eval metrics for ``output_support_tfidf`` and related scores.

    Args:
        text_a: First string.
        text_b: Second string.

    Returns:
        TF-IDF cosine similarity in [0.0, 1.0].  Returns 0.0 if either
        input is empty.
    """
    if not text_a.strip() or not text_b.strip():
        return 0.0
    vecs = _tfidf_vectors([text_a, text_b])
    if len(vecs) < 2:
        return 0.0
    return round(_sparse_cosine(vecs[0], vecs[1]), 4)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Context Attribution
# ─────────────────────────────────────────────────────────────────────────────

def compute_context_attribution(
    model_output: str,
    contexts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Rank retrieved context chunks by their lexical influence on the model output.

    For each context chunk this function computes two complementary scores:

    ``influence_score``
        TF-IDF cosine similarity between the chunk text and the model output.
        Measures how much the vocabulary of this chunk is reflected in the
        answer.  High values indicate the chunk was a primary content source.

    ``loo_impact``
        Leave-one-out delta: (similarity of output to ALL contexts) minus
        (similarity of output to all contexts EXCLUDING this chunk).
        Positive values indicate the chunk contributed positively to the
        aggregate grounding signal.  Negative values are rare but indicate
        the chunk may have introduced vocabulary that distracted from the core
        answer.

    The returned list is sorted by ``influence_score`` descending so the most
    influential chunk appears first, making it easy to populate the evidence
    pack's "Top Sources" section.

    Args:
        model_output:
            The complete text response generated by the model.
        contexts:
            List of retrieved context dicts.  Each dict may contain any of:
            ``title``, ``snippet``, ``text``, ``content``, ``chunk_text``.
            The merge logic concatenates all non-empty string values found
            under these keys to form the chunk's representative text.

    Returns:
        A list of attribution dicts, one per non-empty context chunk, each
        containing:

        - ``chunk_index``   (int)   — original position in the contexts list
        - ``title``         (str)   — chunk title or "Context {n}"
        - ``influence_score`` (float) — TF-IDF cosine vs. model output [0, 1]
        - ``loo_impact``    (float) — LOO delta vs. aggregate coverage [−1, 1]
        - ``rank``          (int)   — rank by influence_score (1 = highest)

        Returns an empty list if ``model_output`` is empty or no non-empty
        context chunks are found.
    """
    if not model_output.strip() or not contexts:
        return []

    # Extract a single representative text string from each context dict.
    # The key priority order mirrors _context_texts() in eval/metrics.
    chunk_texts: list[str] = []
    chunk_titles: list[str] = []
    for idx, item in enumerate(contexts):
        if not isinstance(item, dict):
            chunk_texts.append("")
            chunk_titles.append(f"Context {idx + 1}")
            continue
        merged = " ".join(
            str(item.get(key, "")).strip()
            for key in ("title", "snippet", "text", "content", "chunk_text")
            if str(item.get(key, "")).strip()
        )
        chunk_texts.append(merged)
        chunk_titles.append(str(item.get("title", f"Context {idx + 1}")) or f"Context {idx + 1}")

    # Baseline: similarity of model_output to all chunks concatenated.
    full_context_text = " ".join(t for t in chunk_texts if t)
    baseline_sim = _tfidf_cosine_sim(model_output, full_context_text) if full_context_text else 0.0

    results: list[dict[str, Any]] = []
    for idx, (chunk_text, title) in enumerate(zip(chunk_texts, chunk_titles)):
        if not chunk_text:
            continue

        # Individual influence: how much does this chunk's vocabulary appear in output?
        influence = _tfidf_cosine_sim(model_output, chunk_text)

        # LOO impact: how much does aggregate similarity drop when this chunk is absent?
        remaining = " ".join(t for i, t in enumerate(chunk_texts) if i != idx and t)
        loo_sim = _tfidf_cosine_sim(model_output, remaining) if remaining else 0.0
        loo_impact = round(baseline_sim - loo_sim, 4)

        results.append({
            "chunk_index": idx,
            "title": title,
            "influence_score": round(influence, 4),
            "loo_impact": loo_impact,
        })

    # Sort by influence_score descending and assign rank.
    results.sort(key=lambda x: x["influence_score"], reverse=True)
    for rank, entry in enumerate(results, start=1):
        entry["rank"] = rank

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 2. LIME-style Leave-One-Out Prompt Attribution
# ─────────────────────────────────────────────────────────────────────────────

def _loo_attribution_scores(
    sentences: list[str],
    model_output: str,
) -> list[float]:
    """
    Compute raw LOO attribution scores for every sentence segment.

    For each sentence at position i, the attribution score is:

        score_i = sim(output, full_prompt) − sim(output, prompt_without_sentence_i)

    where sim() is TF-IDF cosine similarity.

    Positive scores indicate the sentence increased output alignment when
    present (it contributed vocabulary that appears in the response).
    Negative scores indicate removing the sentence *improved* alignment
    (the sentence introduced irrelevant vocabulary that diluted the signal).

    Args:
        sentences:    List of sentence strings from the prompt.
        model_output: The model's generated response.

    Returns:
        A list of raw (unrounded) LOO attribution floats, one per sentence.
        All values are 0.0 if ``model_output`` or ``sentences`` is empty.
    """
    if not sentences or not model_output.strip():
        return [0.0] * len(sentences)

    full_prompt = " ".join(sentences)
    baseline = _tfidf_cosine_sim(model_output, full_prompt)

    scores: list[float] = []
    for i in range(len(sentences)):
        # Reconstruct prompt without sentence i, preserving original order.
        prompt_without = " ".join(s for j, s in enumerate(sentences) if j != i)
        if not prompt_without.strip():
            # Edge case: only one sentence in the prompt.
            scores.append(baseline)
        else:
            sim_without = _tfidf_cosine_sim(model_output, prompt_without)
            scores.append(baseline - sim_without)

    return scores


def compute_lime_attribution(
    prompt: str,
    model_output: str,
    n_bootstrap: int = _LOO_BOOTSTRAP_SAMPLES,
) -> dict[str, Any]:
    """
    Compute LIME-style leave-one-out attribution scores for each prompt sentence.

    Algorithm (inspired by LIME, Ribeiro et al. 2016):
      1. Split the prompt into sentence segments.
      2. For each sentence, compute its LOO attribution score: the drop in
         TF-IDF cosine similarity between ``model_output`` and the prompt when
         that sentence is removed.  Higher scores mean higher influence.
      3. Bootstrap over sentence subsets to estimate 95% confidence intervals
         on each score, quantifying how stable the ranking is when the prompt
         composition varies.

    The TF-IDF scoring function acts as a transparent, inspectable proxy for
    "how much does this sentence contribute to the output's vocabulary?"  For
    governance purposes this is the question reviewers most need answered.

    Unlike full LIME (which fits a weighted linear model over thousands of
    random perturbations), LOO attribution is exact for the leave-one-out
    neighbourhood and requires no random sampling for the point estimates.
    Bootstrap CIs are added to give reviewers a sense of score stability.

    Args:
        prompt:
            The complete user prompt sent to the model.
        model_output:
            The model's response text.
        n_bootstrap:
            Number of bootstrap iterations for CI estimation.  Defaults to
            ``_LOO_BOOTSTRAP_SAMPLES`` (200).

    Returns:
        A dict with keys:

        - ``method``        (str)   — always "lime_loo_attribution"
        - ``reference``     (str)   — LIME paper URL
        - ``baseline_sim``  (float) — TF-IDF cosine of output vs. full prompt
        - ``segment_count`` (int)   — number of sentence segments analysed
        - ``segments``      (list)  — per-sentence attribution dicts, each with:
              ``index``       (int)   — position in original prompt
              ``text``        (str)   — sentence text (truncated to 160 chars)
              ``attribution`` (float) — LOO score; positive = influential
              ``ci_95``       (list)  — [lower, upper] 95% bootstrap CI

        Returns a zeroed-out payload if the prompt or output is empty.
    """
    if not prompt.strip() or not model_output.strip():
        return {
            "method": "lime_loo_attribution",
            "reference": "https://arxiv.org/abs/1602.04938",
            "baseline_sim": 0.0,
            "segment_count": 0,
            "segments": [],
            "note": "No analysis: prompt or model output was empty.",
        }

    sentences = _split_sentences(prompt)
    if not sentences:
        return {
            "method": "lime_loo_attribution",
            "reference": "https://arxiv.org/abs/1602.04938",
            "baseline_sim": 0.0,
            "segment_count": 0,
            "segments": [],
            "note": "No analysis: prompt produced no sentence segments above minimum token threshold.",
        }

    full_prompt = " ".join(sentences)
    baseline_sim = round(_tfidf_cosine_sim(model_output, full_prompt), 4)
    raw_scores = _loo_attribution_scores(sentences, model_output)

    # Bootstrap confidence intervals.
    # Strategy: resample the sentence indices with replacement, recompute LOO
    # attributions on the resampled set, collect the distribution of scores
    # for each original position, then extract 2.5th and 97.5th percentiles.
    rng = Random(_RNG_SEED)
    bootstrap_scores: list[list[float]] = [[] for _ in sentences]
    n = len(sentences)

    for _ in range(n_bootstrap):
        # Draw n sentence indices with replacement (bootstrap resample).
        indices = [rng.randrange(n) for _ in range(n)]
        resampled = [sentences[i] for i in indices]
        resampled_scores = _loo_attribution_scores(resampled, model_output)
        # Map bootstrap scores back to original sentence positions via the
        # sampled index mapping.  Each original sentence accumulates bootstrap
        # scores from all the times it was drawn in the resample.
        seen: dict[int, list[float]] = {}
        for pos, original_idx in enumerate(indices):
            seen.setdefault(original_idx, []).append(resampled_scores[pos])
        for original_idx, score_list in seen.items():
            bootstrap_scores[original_idx].extend(score_list)

    def _ci(score_list: list[float]) -> list[float]:
        """Extract 95% bootstrap CI from a sorted score list."""
        if len(score_list) < 4:
            return [0.0, 0.0]
        score_list.sort()
        lo = score_list[max(0, int(0.025 * len(score_list)))]
        hi = score_list[min(len(score_list) - 1, int(0.975 * len(score_list)))]
        return [round(lo, 4), round(hi, 4)]

    segment_dicts: list[dict[str, Any]] = []
    for i, (sentence, score) in enumerate(zip(sentences, raw_scores)):
        segment_dicts.append({
            "index": i,
            "text": sentence[:160] + ("…" if len(sentence) > 160 else ""),
            "attribution": round(score, 4),
            "ci_95": _ci(bootstrap_scores[i]),
        })

    # Sort by attribution descending for the governance summary view.
    segment_dicts.sort(key=lambda x: x["attribution"], reverse=True)

    return {
        "method": "lime_loo_attribution",
        "reference": "https://arxiv.org/abs/1602.04938",
        "baseline_sim": baseline_sim,
        "segment_count": len(sentences),
        "segments": segment_dicts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. SHAP-style Shapley Value Attribution
# ─────────────────────────────────────────────────────────────────────────────

def _characteristic_function(
    coalition_indices: set[int],
    sentences: list[str],
    model_output: str,
) -> float:
    """
    Evaluate the characteristic function v(S) for a coalition of sentences.

    v(S) is defined as the TF-IDF cosine similarity between the model output
    and the text formed by concatenating only the sentences in coalition S.
    This is the "game value" that Shapley values partition among the players
    (sentences).

    v(∅) = 0.0  (no sentences → no similarity signal).

    Args:
        coalition_indices: Set of sentence indices included in this coalition.
        sentences:         Full list of prompt sentences.
        model_output:      The model's generated response.

    Returns:
        TF-IDF cosine similarity in [0.0, 1.0].  Returns 0.0 for empty
        coalitions or empty inputs.
    """
    if not coalition_indices:
        return 0.0
    # Build coalition text in original sentence order to ensure v(S) is
    # order-independent (bag-of-words TF-IDF handles this naturally, but
    # original ordering keeps the text grammatically coherent for debugging).
    coalition_text = " ".join(
        sentences[j] for j in range(len(sentences)) if j in coalition_indices
    )
    return _tfidf_cosine_sim(model_output, coalition_text)


def _shapley_exact(sentences: list[str], model_output: str) -> list[float]:
    """
    Compute exact Shapley values via exhaustive coalition enumeration.

    Uses bitmask enumeration over all 2^N subsets to precompute v(S) for
    every possible coalition, then applies the Shapley formula:

        φ_i = Σ_{S ⊆ N\\{i}} [ |S|! (n − |S| − 1)! / n! ] × [v(S ∪ {i}) − v(S)]

    This is O(2^N × N) in time and O(2^N) in space.  Only called when
    N ≤ _SHAPLEY_EXACT_MAX_SEGMENTS (default 8), giving ≤ 256 subsets.

    Args:
        sentences:    Sentence segments from the prompt (N ≤ 8).
        model_output: The model's generated response.

    Returns:
        A list of exact Shapley values, one per sentence.  Values sum to
        v(full coalition) − v(∅) = baseline_sim − 0 = baseline_sim
        (efficiency property).
    """
    n = len(sentences)
    factorial_n = math.factorial(n)

    # Precompute the characteristic function for every coalition (bitmask).
    # coalition_scores[mask] = v(S) where bit j of mask encodes whether
    # sentence j is in the coalition.
    coalition_scores: dict[int, float] = {}
    for mask in range(1 << n):
        coalition = {j for j in range(n) if mask & (1 << j)}
        coalition_scores[mask] = _characteristic_function(coalition, sentences, model_output)

    shapley: list[float] = []
    for i in range(n):
        bit_i = 1 << i
        phi_i = 0.0

        # Iterate over all subsets S that do NOT contain i.
        for mask in range(1 << n):
            if mask & bit_i:
                # Skip: this subset already contains sentence i.
                continue

            s_size = bin(mask).count("1")
            # Shapley weight for coalition size s_size:
            # w = |S|! × (n − |S| − 1)! / n!
            weight = math.factorial(s_size) * math.factorial(n - s_size - 1) / factorial_n
            # Marginal contribution of sentence i to this coalition.
            phi_i += weight * (coalition_scores[mask | bit_i] - coalition_scores[mask])

        shapley.append(phi_i)

    return shapley


def _shapley_monte_carlo(
    sentences: list[str],
    model_output: str,
    n_samples: int = _SHAPLEY_MC_SAMPLES,
    rng_seed: int = _RNG_SEED,
) -> list[float]:
    """
    Estimate Shapley values via Monte Carlo permutation sampling.

    Algorithm (Strumbelj & Kononenko, 2014 approximation of Lundberg & Lee):
      For each of n_samples iterations:
        1. Sample a uniformly random permutation of all N sentence indices.
        2. Step through the permutation; maintain a growing coalition S.
        3. When sentence i is added, record its marginal contribution:
               v(S ∪ {i}) − v(S)
           where S is the set of sentences that appeared BEFORE i in this
           permutation.
        4. After n_samples iterations, φ_i is the running mean of all
           marginal contributions recorded for sentence i.

    The marginal contribution v(S ∪ {i}) − v(S) is computed using the
    characteristic function at each step (TF-IDF cosine with the model output).
    Coalition text is built in original sentence index order (not permutation
    order) to ensure v(S) is consistent with the exact implementation.

    Args:
        sentences: Sentence segments from the prompt.
        model_output: The model's generated response.
        n_samples: Number of random permutation samples (default 300).
        rng_seed: RNG seed for reproducibility (default 42).

    Returns:
        A list of estimated Shapley values, one per sentence.  Values
        approximately satisfy the efficiency axiom: Σ φ_i ≈ baseline_sim.
    """
    n = len(sentences)
    rng = Random(rng_seed)
    # Accumulate marginal contributions over all sampled permutations.
    running_sum = [0.0] * n

    for _ in range(n_samples):
        perm = list(range(n))
        rng.shuffle(perm)

        coalition: set[int] = set()
        v_prev = 0.0  # v(∅) = 0

        for idx in perm:
            coalition.add(idx)
            # Evaluate v(S ∪ {idx}) with the coalition in original index order.
            v_curr = _characteristic_function(coalition, sentences, model_output)
            # Marginal contribution of sentence idx given the predecessors in perm.
            running_sum[idx] += v_curr - v_prev
            v_prev = v_curr

    # Average over all sampled permutations to get the Shapley estimate.
    return [running_sum[i] / n_samples for i in range(n)]


def compute_shapley_attribution(
    prompt: str,
    model_output: str,
) -> dict[str, Any]:
    """
    Compute SHAP-style Shapley value attribution for each prompt sentence.

    Shapley values from cooperative game theory assign a unique "fair credit"
    to each sentence based on its average marginal contribution across all
    possible orderings.  They are the only attribution method that
    simultaneously satisfies:

      - **Efficiency**:  Σ φ_i = v(full prompt) − v(∅).
      - **Symmetry**:    Sentences with equal impact receive equal attribution.
      - **Dummy**:       A sentence that contributes nothing gets φ = 0.
      - **Linearity**:   Attribution is additive over independent games.

    For prompts with ≤ _SHAPLEY_EXACT_MAX_SEGMENTS sentences, exact values are
    computed via exhaustive coalition enumeration.  Longer prompts use Monte
    Carlo permutation sampling (300 samples by default).

    Args:
        prompt:
            The complete user prompt sent to the model.
        model_output:
            The model's generated response.

    Returns:
        A dict with keys:

        - ``method``         (str)  — "shapley_exact" or "shapley_monte_carlo"
        - ``reference``      (str)  — SHAP paper URL
        - ``efficiency_sum`` (float)— Σ φ_i (should ≈ baseline_sim)
        - ``baseline_sim``   (float)— TF-IDF cosine of output vs. full prompt
        - ``segment_count``  (int)  — number of sentence segments
        - ``segments``       (list) — per-sentence dicts, each with:
              ``index``        (int)   — position in original prompt
              ``text``         (str)   — sentence text (truncated to 160 chars)
              ``shapley_value``(float) — credit assigned [approx −1, +1]
              ``normalised``   (float) — φ_i / Σ|φ_j| (relative importance %)

        Returns a zeroed-out payload if prompt or output is empty.
    """
    if not prompt.strip() or not model_output.strip():
        return {
            "method": "shapley_monte_carlo",
            "reference": "https://arxiv.org/abs/1705.07874",
            "efficiency_sum": 0.0,
            "baseline_sim": 0.0,
            "segment_count": 0,
            "segments": [],
            "note": "No analysis: prompt or model output was empty.",
        }

    sentences = _split_sentences(prompt)
    if not sentences:
        return {
            "method": "shapley_monte_carlo",
            "reference": "https://arxiv.org/abs/1705.07874",
            "efficiency_sum": 0.0,
            "baseline_sim": 0.0,
            "segment_count": 0,
            "segments": [],
            "note": "No analysis: prompt produced no sentence segments above minimum token threshold.",
        }

    n = len(sentences)
    full_prompt = " ".join(sentences)
    baseline_sim = round(_tfidf_cosine_sim(model_output, full_prompt), 4)

    # Choose exact vs. Monte Carlo based on prompt length.
    if n <= _SHAPLEY_EXACT_MAX_SEGMENTS:
        method_name = "shapley_exact"
        raw_values = _shapley_exact(sentences, model_output)
    else:
        method_name = "shapley_monte_carlo"
        raw_values = _shapley_monte_carlo(sentences, model_output)

    # Compute normalised importance: φ_i / Σ|φ_j|.
    # This expresses each sentence's credit as a fraction of total absolute
    # attribution, making values comparable across prompts of different lengths.
    total_abs = sum(abs(v) for v in raw_values)

    segment_dicts: list[dict[str, Any]] = []
    for i, (sentence, phi) in enumerate(zip(sentences, raw_values)):
        normalised = round(abs(phi) / total_abs, 4) if total_abs > 0 else 0.0
        segment_dicts.append({
            "index": i,
            "text": sentence[:160] + ("…" if len(sentence) > 160 else ""),
            "shapley_value": round(phi, 4),
            "normalised": normalised,
        })

    # Sort by absolute Shapley value descending so the most impactful
    # segments appear first in the governance report.
    segment_dicts.sort(key=lambda x: abs(x["shapley_value"]), reverse=True)

    efficiency_sum = round(sum(raw_values), 4)

    return {
        "method": method_name,
        "reference": "https://arxiv.org/abs/1705.07874",
        "efficiency_sum": efficiency_sum,
        "baseline_sim": baseline_sim,
        "segment_count": n,
        "segments": segment_dicts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Counterfactual Summary
# ─────────────────────────────────────────────────────────────────────────────

def compute_counterfactual_summary(
    eval_results: list[dict[str, Any]],
    lineage_nodes: list[dict[str, Any]],
    redteam_summary: dict[str, Any],
    context_attribution: list[dict[str, Any]],
) -> list[str]:
    """
    Synthesise narrative counterfactual statements from existing evidence.

    Counterfactual explanations answer "what would happen if X were different?"
    This function derives such statements from metrics and lineage data already
    computed by the toolkit pipeline, requiring no additional model calls.

    Statement categories generated:

    1. **Source removal impact** — derived from context attribution LOO deltas.
       "If [top source] were absent, aggregate grounding coverage would drop by
       approximately Y%."

    2. **Claim support degradation** — derived from ``claim_support_rate`` in
       eval results.
       "If the retrieved contexts contained no supporting evidence, roughly X
       claims would become unsupported."

    3. **Citation coverage risk** — derived from lineage transparency risk.
       "With current citation coverage of C%, Y% of output claims are at risk
       of being unverifiable by a human reviewer."

    4. **Red-team resistance** — derived from red-team summary findings.
       "Under adversarial perturbation, Y of Z tested attack patterns were
       successfully mitigated."

    5. **Metric threshold counterfactuals** — derived from eval metric results.
       "If [metric] dropped below its threshold of T, the evidence pack would
       require re-evaluation before deployment."

    Args:
        eval_results:
            List of eval result dicts as produced by the reporting pipeline,
            each optionally containing ``metric_results`` and ``suite_name``.
        lineage_nodes:
            List of lineage node dicts (from ``LineageReport.nodes``).
        redteam_summary:
            Red-team summary dict (from ``redteam_summary.json``).
        context_attribution:
            Context attribution list as returned by ``compute_context_attribution``.

    Returns:
        A list of human-readable counterfactual statement strings, suitable
        for inclusion in the reasoning report's "Counterfactual Analysis"
        section.  Returns a generic fallback list if all inputs are empty.
    """
    statements: list[str] = []

    # ── 1. Source removal impact (from context attribution LOO deltas) ──────
    if context_attribution:
        # Find the context chunk with the highest LOO impact.
        top_by_impact = max(context_attribution, key=lambda x: x.get("loo_impact", 0.0))
        top_impact_val = top_by_impact.get("loo_impact", 0.0)
        top_title = top_by_impact.get("title", "the top-ranked context")
        if top_impact_val > 0.001:
            pct = round(top_impact_val * 100, 1)
            statements.append(
                f"If '{top_title}' were absent from retrieved sources, aggregate "
                f"grounding coverage would drop by approximately {pct}% "
                f"(LOO impact = {top_impact_val:.4f})."
            )
        # If multiple chunks have near-zero LOO impact, flag over-concentration risk.
        high_influence = [c for c in context_attribution if c.get("influence_score", 0.0) >= 0.3]
        if len(high_influence) == 1:
            statements.append(
                f"Answer grounding is highly concentrated in a single source "
                f"('{high_influence[0].get('title', 'unknown')}', "
                f"influence = {high_influence[0].get('influence_score', 0.0):.4f}). "
                "Removing or updating this source would materially change the answer."
            )

    # ── 2. Claim support degradation (from eval metric claim_support_rate) ──
    # Walk all eval result dicts looking for the claim_support_rate metric.
    claim_support_rate: float | None = None
    total_claims: int | None = None
    for result in eval_results:
        for metric in result.get("metric_results", []):
            if metric.get("metric_id") == "claim_support_rate":
                claim_support_rate = float(metric.get("value", 0.0))
                total_claims = int(metric.get("details", {}).get("claim_count", 0))
                break
        if claim_support_rate is not None:
            break

    if claim_support_rate is not None and total_claims:
        supported_count = round(claim_support_rate * total_claims)
        unsupported_count = total_claims - supported_count
        statements.append(
            f"If all retrieved contexts were removed, approximately "
            f"{total_claims} output claims would become unverifiable. "
            f"Currently {supported_count} of {total_claims} claims "
            f"({round(claim_support_rate * 100, 1)}%) are evidenced by retrieved sources; "
            f"{unsupported_count} claim(s) already lack direct grounding."
        )

    # ── 3. Citation coverage risk (from lineage transparency risk) ───────────
    # Derive citation coverage from lineage nodes (proxy: ratio of nodes with URIs).
    if lineage_nodes:
        cited = sum(
            1 for n in lineage_nodes
            if n.get("uri") and n.get("node_id", "") != "ctx-none"
        )
        total_nodes = len([n for n in lineage_nodes if n.get("node_id", "") != "ctx-none"])
        if total_nodes > 0:
            coverage = round(cited / total_nodes, 3)
            unverifiable_pct = round((1.0 - coverage) * 100, 1)
            statements.append(
                f"With a citation coverage of {round(coverage * 100, 1)}%, "
                f"approximately {unverifiable_pct}% of source references in the "
                "output cannot be directly verified by a human reviewer without "
                "access to additional documentation."
            )

    # ── 4. Red-team resistance (from redteam_summary) ────────────────────────
    if isinstance(redteam_summary, dict):
        total_cases = int(redteam_summary.get("total_cases", 0))
        passed = int(redteam_summary.get("passed", 0))
        failed = int(redteam_summary.get("failed", 0))
        if total_cases > 0:
            pass_rate = round(passed / total_cases * 100, 1)
            statements.append(
                f"Under adversarial red-team evaluation ({total_cases} attack patterns), "
                f"{passed} of {total_cases} cases were successfully mitigated "
                f"({pass_rate}% resistance rate). "
                f"If the {failed} failing pattern(s) were exploited in production, "
                "the model's output could be manipulated or sensitive data exposed."
            )
        # Highlight critical findings as counterfactual risk signals.
        critical = int(redteam_summary.get("critical_count", 0))
        high = int(redteam_summary.get("high_count", 0))
        if critical > 0 or high > 0:
            statements.append(
                f"If {critical} critical and {high} high-severity red-team findings "
                "were left unmitigated before deployment, the system would be "
                "classified as 'not trusted' and deployment would be blocked by "
                "the governance stage-gate."
            )

    # ── 5. Metric threshold counterfactuals (from eval_results) ─────────────
    # Find metrics that are close to their thresholds (within 10% of failing).
    threshold_risks: list[str] = []
    for result in eval_results:
        for metric in result.get("metric_results", []):
            metric_id = metric.get("metric_id", "")
            raw_value = metric.get("value")
            threshold = metric.get("threshold")
            passed_flag = metric.get("passed")
            # Advisory metrics (e.g. LLM judges under a stub provider) report
            # value=None / passed=None to signal "unavailable"; skip them.
            if raw_value is None or threshold is None or passed_flag is None:
                continue
            value = float(raw_value)
            if isinstance(threshold, (int, float)) and threshold > 0:
                margin = abs(value - float(threshold))
                relative_margin = margin / float(threshold)
                # Report metrics that are passing but within 10% of failing.
                if passed_flag and relative_margin < 0.10:
                    threshold_risks.append(
                        f"Metric '{metric_id}' (value={value:.3f}) is within "
                        f"{round(relative_margin * 100, 1)}% of its threshold "
                        f"({threshold}). A modest degradation in this metric would "
                        "cause the evidence pack to require re-evaluation."
                    )
    statements.extend(threshold_risks)

    # ── Fallback ──────────────────────────────────────────────────────────────
    if not statements:
        statements.append(
            "Insufficient evaluation data to generate concrete counterfactual "
            "statements for this run.  Run a full evaluation suite and red-team "
            "scan to enable counterfactual analysis."
        )

    return statements


# ─────────────────────────────────────────────────────────────────────────────
# LLM narrative explanation (Tim2 — Option A)
# ─────────────────────────────────────────────────────────────────────────────
#
# This function asks a configured LLM to write a short rationale for the
# deterministic scores already on the scorecard.  The narrative is *additive*
# — it never modifies the underlying numbers, never gates the verdict, and is
# omitted entirely when no live adapter is configured.  Reproducibility is
# preserved by routing the call through invoke_model_safely with
# deterministic=True (temperature=0, fixed seed) and caching by prompt hash.
#
# What the model is asked to do:
#   * Explain in plain language what the metric values mean for THIS answer
#   * Highlight any tension between the metrics
#   * NOT propose a different verdict — only explain the current one
#   * NOT speculate about facts not present in the evidence

_LLM_NARRATIVE_CACHE: dict[str, str] = {}

# Module-level binding so tests can monkeypatch `explainability.invoke_model_safely`.
# A local import inside the function would create a fresh binding on each call
# that bypassed monkeypatching.  model_client is a leaf module (only imports
# from schemas), so importing it at module scope here introduces no cycle.
from trusted_ai_toolkit.model_client import invoke_model_safely  # noqa: E402


def compute_llm_narrative(
    config: Any,
    verdict: str | None,
    reasons: list[str],
    metric_summary: dict[str, Any],
    model_output: str,
    contexts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a plain-language rationale for the deterministic verdict.

    Returns ``{available, narrative, model, cache_hit}``.  When the configured
    adapter is ``stub`` or any failure occurs, ``available`` is False and
    ``narrative`` is None — the template renders a fallback note and the
    pipeline continues unaffected.

    Parameters
    ----------
    config:
        ToolkitConfig.  Typed as Any here to avoid a runtime circular import.
    verdict:
        The deterministic verdict string.  Presented to the LLM as a fact
        to explain, never as a decision to revisit.
    reasons:
        The list of reason strings already attached to the verdict.
    metric_summary:
        ``metric_name → value`` for the four answer-trust metrics, plus an
        optional ``bias_signal_count`` key.
    model_output:
        The model's response text (truncated before sending).
    contexts:
        Retrieved context chunks for evidence excerpting (optional).
    """

    if config is None or getattr(config.adapters, "provider", "stub") == "stub":
        return {"available": False, "narrative": None, "model": None, "cache_hit": False}

    metric_lines: list[str] = []
    for key, value in metric_summary.items():
        if value is None:
            continue
        if isinstance(value, float):
            metric_lines.append(f"  - {key}: {value:.3f}")
        else:
            metric_lines.append(f"  - {key}: {value}")
    metrics_block = "\n".join(metric_lines) if metric_lines else "  (no metrics measured)"

    reason_lines = "\n".join(f"  - {r}" for r in reasons[:6]) if reasons else "  (no reasons provided)"

    excerpt = ""
    if isinstance(contexts, list) and contexts:
        first = contexts[0]
        if isinstance(first, dict):
            chunk_text = " ".join(
                str(first.get(field, ""))
                for field in ("title", "snippet", "text", "content")
                if first.get(field)
            ).strip()
            if chunk_text:
                excerpt = chunk_text[:600]

    prompt = (
        "You are an AI governance reviewer. A deterministic evaluation pipeline "
        "has produced the verdict and metric values shown below for a model "
        "answer. Your task is to write a SHORT (two paragraphs, ~120 words "
        "total) plain-language rationale that explains what the metrics mean "
        "for this specific answer.\n\n"
        "STRICT RULES:\n"
        "1. Do NOT propose a different verdict — explain the existing one only.\n"
        "2. Do NOT introduce facts that are not in the evidence below.\n"
        "3. Do highlight any tension between the metrics (e.g. high lexical "
        "support but a contradiction signal).\n"
        "4. Address a non-technical compliance reviewer.\n\n"
        f"VERDICT: {verdict or 'unknown'}\n\n"
        f"DETERMINISTIC REASONS:\n{reason_lines}\n\n"
        f"METRIC VALUES:\n{metrics_block}\n\n"
        f"MODEL ANSWER (truncated):\n{model_output[:800]}\n\n"
        f"BEST-MATCHED EVIDENCE EXCERPT:\n{excerpt or '(none provided)'}\n\n"
        "Now write the two-paragraph rationale."
    )

    cache_key = str(hash(prompt))
    if cache_key in _LLM_NARRATIVE_CACHE:
        return {
            "available": True,
            "narrative": _LLM_NARRATIVE_CACHE[cache_key],
            "model": getattr(config.adapters, "model", None)
            or getattr(getattr(config, "system", None), "model_name", None),
            "cache_hit": True,
        }

    result = invoke_model_safely(prompt, config, deterministic=True)
    if result is None:
        return {"available": False, "narrative": None, "model": None, "cache_hit": False}

    narrative = result.output_text.strip()
    _LLM_NARRATIVE_CACHE[cache_key] = narrative
    return {
        "available": True,
        "narrative": narrative,
        "model": result.model,
        "cache_hit": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator — run all XAI methods and return a unified payload
# ─────────────────────────────────────────────────────────────────────────────

def run_xai_analysis(
    prompt: str,
    model_output: str,
    contexts: list[dict[str, Any]],
    eval_results: list[dict[str, Any]],
    lineage_nodes: list[dict[str, Any]],
    redteam_summary: dict[str, Any],
) -> dict[str, Any]:
    """
    Orchestrate all XAI engines and return a unified explainability payload.

    This is the primary entry point called by ``generate_reasoning_report``.
    It runs the four XAI methods in sequence and assembles their outputs into
    a single dict suitable for Jinja2 template rendering and JSON serialisation.

    Execution order and rationale:
      1. ``compute_context_attribution`` first — cheapest, always produces signal.
      2. ``compute_lime_attribution`` second — requires only prompt + output.
      3. ``compute_shapley_attribution`` third — more expensive; benefits from the
         sentence segmentation already done in LIME.
      4. ``compute_counterfactual_summary`` last — depends on the context
         attribution results computed in step 1.

    All methods are designed to be safe-by-default: they return zeroed-out
    payloads for missing inputs rather than raising exceptions, so an
    incomplete evidence pack will still produce a valid (if partial) report.

    Args:
        prompt:
            The complete prompt sent to the model.
        model_output:
            The model's generated response text.
        contexts:
            Retrieved context chunk dicts from ``prompt_run.json``.
        eval_results:
            Eval metric result dicts from the evidence pack.
        lineage_nodes:
            Lineage node dicts from the lineage report.
        redteam_summary:
            Red-team summary dict from the evidence pack.

    Returns:
        A dict with top-level keys:

        - ``context_attribution``    (list)  — per-chunk influence scores
        - ``lime_attribution``        (dict)  — LIME LOO attribution payload
        - ``shapley_attribution``     (dict)  — Shapley value payload
        - ``counterfactual_summary``  (list)  — narrative counterfactuals
        - ``xai_available``           (bool)  — True if any analysis ran
        - ``method_labels``           (list)  — human-readable method names
    """
    ctx_attr = compute_context_attribution(model_output, contexts)
    lime_attr = compute_lime_attribution(prompt, model_output)
    shapley_attr = compute_shapley_attribution(prompt, model_output)
    cf_summary = compute_counterfactual_summary(
        eval_results=eval_results,
        lineage_nodes=lineage_nodes,
        redteam_summary=redteam_summary,
        context_attribution=ctx_attr,
    )

    xai_available = bool(
        ctx_attr
        or lime_attr.get("segment_count", 0) > 0
        or shapley_attr.get("segment_count", 0) > 0
    )

    return {
        "context_attribution": ctx_attr,
        "lime_attribution": lime_attr,
        "shapley_attribution": shapley_attr,
        "counterfactual_summary": cf_summary,
        "xai_available": xai_available,
        "method_labels": [
            "Context Attribution (TF-IDF leave-one-out, per retrieved chunk)",
            "LIME-style Feature Attribution (leave-one-out prompt segmentation, Ribeiro et al. 2016)",
            "SHAP-style Shapley Values (Monte Carlo permutation sampling, Lundberg & Lee 2017)",
            "Counterfactual Analysis (evidence-gap narratives from eval metrics and lineage)",
        ],
    }
