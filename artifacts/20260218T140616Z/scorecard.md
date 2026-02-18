# Trusted AI Scorecard

**Project:** sample-trusted-ai-project  
**Run ID:** 20260218T140616Z  
**Risk Tier:** medium  
**Overall Status:** needs_review

## Executive Summary

This governance scorecard summarizes model quality, fairness indicators, security posture, and documentation readiness for release review.

## Risk Statement

Final deployment approval requires human review of high-risk findings, business impact, and legal/compliance obligations.

## Responsible AI Dimension Status

| Dimension | Status |
|---|---|
| Fairness | insufficient_evidence |
| Reliability and Safety | provisionally_met |
| Privacy and Security | needs_action |
| Transparency | provisionally_met |
| Accountability | provisionally_met |
| Inclusiveness | insufficient_evidence |

## Metrics Table

| Metric | Value | Threshold | Pass |
|---|---:|---:|:---:|
| accuracy_stub | 0.81 | 0.7 | True |
| reliability | 0.83 | 0.75 | True |


## Red Team Summary

- Severity Threshold: high
- Low: 0
- Medium: 1
- High: 2
- Critical: 1

## Governance Control Checklist

| Control | Status |
|---|---|
| Defined Intended Use | yes |
| Documented Limitations | yes |
| Evaluation Thresholds Defined | yes |
| Red-Team Security Testing Completed | yes |
| Explainability Report Available | yes |
| Human Sign-Off Recorded | pending |


## Required Actions and Next Steps


- Mitigate high/critical red-team findings before deployment.


## Artifact Links


- eval_results: `artifacts/20260218T140011Z/eval_results.json`

- redteam_findings: `artifacts/20260218T140011Z/redteam_findings.json`

- reasoning_report: `artifacts/20260218T140616Z/reasoning_report.md`
