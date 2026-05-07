"""Unit tests for the polarity-mismatch contradiction heuristic.

Regression: pre-fix, ``_claim_analysis`` ran ``_negation_polarity`` over the
entire matched chunk.  A stray negation token in an unrelated sentence
(extremely common in policy / legal / governance evidence) flipped the
chunk's polarity and falsely flagged a supported claim as contradicted.
Even a single false-positive contradiction in 10 claims produced a
~13 % drop on the user-facing trust score via Stage 3's multiplicative
penalty.

The fix localises the polarity check to the best-matching sentence
within the chunk.  These tests pin that behaviour.
"""

from __future__ import annotations

from trusted_ai_toolkit.eval.metrics import _best_evidence_span, _claim_analysis


def test_unrelated_negation_in_chunk_no_longer_flags_contradiction() -> None:
    """Pre-fix false-positive: claim is supported by sentence A in the chunk;
    sentence B happens to contain "not" referring to a different topic.  The
    polarity check should look at sentence A, not the whole chunk."""
    output = "Reviewers must approve all changes."
    contexts = [
        # First sentence supports the claim verbatim.  Second sentence has a
        # negation token but about a different topic — it must not flip the
        # polarity of the supporting evidence.
        "Reviewers must approve all changes. Some reports do not require sign-off."
    ]
    analysis = _claim_analysis(output, contexts)
    assert analysis["claim_count"] == 1
    assert analysis["contradicted_count"] == 0
    assert analysis["claims"][0]["status"] == "supported"


def test_real_contradiction_in_best_matching_sentence_still_flagged() -> None:
    """When the best-matching sentence itself disagrees on polarity, the
    contradiction must still fire.  Claim asserts an action; the closest
    sentence in the evidence denies that same action."""
    output = "Reviewers must approve all changes."
    contexts = [
        # The best lexical match for the claim is the first sentence, and it
        # has the opposite polarity ("must not approve").  Trailing sentence
        # is unrelated noise.
        "Reviewers must not approve any changes outside business hours. Logs are kept for audit."
    ]
    analysis = _claim_analysis(output, contexts)
    assert analysis["claim_count"] == 1
    assert analysis["contradicted_count"] == 1
    assert analysis["claims"][0]["status"] == "contradicted"


def test_single_sentence_chunk_preserves_legacy_behavior() -> None:
    """Degenerate input — chunk with one sentence — must still detect a
    polarity mismatch (collapses to the old chunk-level behaviour)."""
    output = "Manual approval is required."
    contexts = ["Manual approval is not required for this category."]
    analysis = _claim_analysis(output, contexts)
    assert analysis["claim_count"] == 1
    assert analysis["contradicted_count"] == 1


def test_best_evidence_span_picks_topical_sentence() -> None:
    """_best_evidence_span returns the sentence in the chunk whose tokens
    overlap most with the claim — not the first or last sentence."""
    claim = "Stakeholders must sign off before release."
    matched_context = (
        "The deployment runs every Monday. "
        "Stakeholders must sign off before release. "
        "Logs are retained for ninety days."
    )
    span = _best_evidence_span(claim, matched_context)
    assert "stakeholders must sign off" in span.lower()


def test_best_evidence_span_falls_back_when_no_overlap() -> None:
    """When no sentence shares tokens with the claim, the helper returns
    the whole chunk so callers don't operate on an arbitrary sentence."""
    claim = "Reviewers must approve all changes."
    matched_context = "Weather is nice today. The dog walked the park."
    span = _best_evidence_span(claim, matched_context)
    # Whole chunk preserved (not a single sentence picked at random).
    assert span == matched_context


def test_best_evidence_span_handles_short_input() -> None:
    """One-sentence or empty inputs degrade gracefully to chunk-level."""
    assert _best_evidence_span("anything", "") == ""
    assert _best_evidence_span("anything", "Single sentence chunk.") == "Single sentence chunk."
