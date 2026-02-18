# Trusted AI Scorecard

**Project:** sample-trusted-ai-project  
**Run ID:** 20260218T140934Z  
**Risk Tier:** Medium  
**Overall Status:** Needs Review

## Executive Summary

This governance scorecard summarizes model quality, fairness indicators, security posture, and documentation readiness for release review.

## Risk Statement

Final deployment approval requires human review of high-risk findings, business impact, and legal/compliance obligations.

## Responsible AI Dimension Status

| Dimension | Status |
|---|---|
| Fairness | Insufficient Evidence |
| Reliability and Safety | Provisionally Met |
| Privacy and Security | Needs Action |
| Transparency | Provisionally Met |
| Accountability | Provisionally Met |
| Inclusiveness | Insufficient Evidence |

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
| Defined Intended Use | Yes |
| Documented Limitations | Yes |
| Evaluation Thresholds Defined | Yes |
| Red-Team Security Testing Completed | Yes |
| Explainability Report Available | Yes |
| Human Sign-Off Recorded | Pending |


## Required Actions and Next Steps


- Mitigate high/critical red-team findings before deployment.


## Artifact Links


- eval_results: `artifacts/20260218T140011Z/eval_results.json`

- redteam_findings: `artifacts/20260218T140011Z/redteam_findings.json`

- reasoning_report: `artifacts/20260218T140703Z/reasoning_report.md`
