# KentroXAI Demo Kit

This folder contains a complete walkthrough for demonstrating the KentroXAI lifecycle from question intake to governed artifact generation.

Recommended order:

1. Open `demo/index.html`
2. Read `demo/DEMO_WALKTHROUGH.md`
3. Keep `demo/ARTIFACT_GUIDE.md` nearby for artifact-specific questions
4. Use `demo/LIVE_DEMO_CHECKLIST.md` before the live demo starts

What this demo covers:

- high-level system overview
- end-to-end runtime lifecycle
- answer trust and release-governance separation
- artifact generation and who each artifact is for
- live demo talk track
- operational checklist for Databricks and the app
- directory and file references for each major lifecycle stage

Primary repo areas referenced by this demo:

- `apps/kentro-chat`
- `rag_answer_trust_job.py`
- `src/trusted_ai_toolkit/cli.py`
- `src/trusted_ai_toolkit/eval/runner.py`
- `src/trusted_ai_toolkit/eval/metrics/__init__.py`
- `src/trusted_ai_toolkit/reporting.py`
- `src/trusted_ai_toolkit/redteam/runner.py`
- `src/trusted_ai_toolkit/xai/lineage.py`
- `src/trusted_ai_toolkit/xai/reasoning_report.py`

Directory quick reference:

- App UI and backend:
  - `apps/kentro-chat/`
- Databricks job entry:
  - `rag_answer_trust_job.py`
- Core toolkit package:
  - `src/trusted_ai_toolkit/`
- Deterministic controls package:
  - `src/tat/`
- Evaluation suite definitions:
  - `suites/`
- Built-in evaluation suite copies:
  - `src/trusted_ai_toolkit/eval/suites/`
- Templates used for rendered artifacts:
  - `src/trusted_ai_toolkit/templates/`
- Example outputs:
  - `sample_evidence_pack/20260218T143752Z/`

Reference sample evidence pack:

- `sample_evidence_pack/20260218T143752Z`
