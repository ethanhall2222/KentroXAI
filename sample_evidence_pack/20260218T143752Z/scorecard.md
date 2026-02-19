# Trusted AI Scorecard

**Project:** sample-trusted-ai-project  
**Run ID:** 20260218T143752Z  
**Risk Tier:** Medium  
**Overall Status:** Pass  
**Go/No-Go:** GO

## Executive Summary

This governance scorecard summarizes model quality, fairness indicators, security posture, and documentation readiness for release review.

## Stage Gate Status

| Stage Gate | Status |
|---|---|
| evaluation | pass |
| redteam | pass |
| documentation | pass |
| monitoring | pass |


## Evidence Pack Completeness

- Completeness: 93.33%
- Required Outputs: 15

## Responsible AI Dimension Status

| Dimension | Status |
|---|---|
| Fairness | Provisionally Met |
| Reliability and Safety | Provisionally Met |
| Privacy and Security | Provisionally Met |
| Transparency | Provisionally Met |
| Accountability | Provisionally Met |
| Inclusiveness | Insufficient Evidence |

## Fairness Snapshot (AIF360-Inspired)

- Statistical Parity Difference target: `abs(SPD) <= threshold`
- Disparate Impact Ratio target: `DIR >= 0.8` (80% rule heuristic)
- Equal Opportunity Difference target: `abs(EOD) <= threshold`
- Average Odds Difference target: `abs(AOD) <= threshold`
- Reference: https://github.com/Trusted-AI/AIF360

## Metrics Table

| Metric | Value | Threshold | Pass |
|---|---:|---:|:---:|
| accuracy_stub | 0.81 | 0.7 | True |
| reliability | 0.83 | 0.75 | True |
| fairness_demographic_parity_diff | 0.14 | 0.2 | True |
| groundedness_stub | 0.72 | 0.6 | True |
| refusal_correctness | 0.902 | 0.8 | True |
| unanswerable_handling | 0.882 | 0.78 | True |


## Red Team Summary

- Severity Threshold: high
- Low: 20
- Medium: 0
- High: 0
- Critical: 0

## Governance Control Checklist

| Control | Status |
|---|---|
| Defined Intended Use | Yes |
| Documented Limitations | Yes |
| Evaluation Thresholds Defined | Yes |
| Red-Team Security Testing Completed | Yes |
| Explainability Report Available | Yes |
| Human Sign-Off Recorded | Pending |


## Required Actions and Next Steps


- No blocking issues in stub checks; proceed to human governance review.


## Artifact Links


- eval_results: `sample_evidence_pack/20260218T143752Z/eval_results.json`

- redteam_findings: `sample_evidence_pack/20260218T143752Z/redteam_findings.json`

- reasoning_report: `sample_evidence_pack/20260218T143752Z/reasoning_report.md`
