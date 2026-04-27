# KentroXAI Lifecycle Demo Walkthrough

## Demo Goal

Show that KentroXAI is not just a chat answer generator. It is a governed answer lifecycle that:

1. receives a user question
2. retrieves evidence
3. generates an answer
4. evaluates answer truth and support
5. runs governance controls and red-team checks
6. produces auditable artifacts
7. returns a release-oriented trust and decision package

## Audience-Friendly One-Liner

`KentroXAI turns one model answer into a full evidence-backed governance package.`

## Suggested Demo Length

- Executive version: 7 to 10 minutes
- Full technical walkthrough: 20 to 30 minutes

## Opening Narrative

Start with this:

`What you are about to see is a governed AI response lifecycle. A user asks a question in the app, the platform generates an answer, evaluates whether that answer is supported by evidence, stress-tests the run, and writes a full evidence pack that can be reviewed by engineering, governance, and risk stakeholders.`

## Part 1: High-Level Architecture

Explain the three main layers:

1. Experience layer
   - `apps/kentro-chat`
   - user enters a question
   - UI shows answer, trust summary, and scorecard

2. Orchestration layer
   - Databricks app backend and Databricks job path
   - `rag_answer_trust_job.py`
   - `src/trusted_ai_toolkit/cli.py`
   - coordinates retrieval, evaluation, artifact writing, and scorecard generation

3. Governance layer
   - evaluation metrics
   - red-team checks
   - monitoring and incident logic
   - explainability and documentation artifacts

Use this phrase:

`The app is the front door. The Databricks job is the execution spine. The toolkit is the governance engine.`

### Directory Reference

- Experience layer:
  - `apps/kentro-chat/frontend/`
  - `apps/kentro-chat/backend/`
- Orchestration layer:
  - `rag_answer_trust_job.py`
  - `src/trusted_ai_toolkit/cli.py`
  - `src/trusted_ai_toolkit/databricks_pipeline.py`
- Governance layer:
  - `src/trusted_ai_toolkit/eval/`
  - `src/trusted_ai_toolkit/redteam/`
  - `src/trusted_ai_toolkit/reporting.py`
  - `src/trusted_ai_toolkit/xai/`
  - `src/trusted_ai_toolkit/documentation.py`

## Part 2: Runtime Lifecycle

Walk the audience through the runtime flow:

1. User asks a question
   - example: `What is deep learning used for?`

2. Retrieval and answer generation
   - the app hands the request to the Databricks job backend
   - the job retrieves relevant chunks and builds the model prompt
   - the model returns an answer

3. Prompt and response artifacts are written
   - `prompt_run.json`
   - retrieved chunks and context metadata are preserved

4. Evaluation runs
   - `run_eval(...)` computes answer-truth and support metrics
   - examples:
     - `claim_support_rate`
     - `unsupported_claim_rate`
     - `contradiction_rate`
     - `evidence_sufficiency_score`
     - `context_relevance_embedding_coverage`
     - `llm_contradiction_judge`
     - `llm_claim_entailment`

5. Red-team and governance checks run
   - deterministic red-team scenarios and severity summaries
   - control-based governance scoring across security, reliability, transparency, and governance

6. Explainability artifacts are created
   - reasoning report
   - lineage report
   - authoritative data index

7. Scorecard is generated
   - answer verdict
   - answer trust score
   - release readiness
   - stage gates
   - required actions

8. Documentation and manifest are built
   - cards, manifests, and audit trail outputs

### File and Folder References By Step

1. User asks a question
   - `apps/kentro-chat/frontend/src/App.tsx`
   - `apps/kentro-chat/frontend/src/components/`

2. Backend receives request
   - `apps/kentro-chat/backend/server.js`

3. Databricks job handoff and answer pipeline
   - `rag_answer_trust_job.py`
   - `src/trusted_ai_toolkit/databricks_pipeline.py`

4. Prompt and runtime artifacts
   - `src/trusted_ai_toolkit/cli.py`
   - output folder: `artifacts/<run_id>/`

5. Evaluation metrics and suites
   - `src/trusted_ai_toolkit/eval/runner.py`
   - `src/trusted_ai_toolkit/eval/metrics/__init__.py`
   - `src/trusted_ai_toolkit/eval/metrics/llm_judges.py`
   - `suites/rag_live.yaml`
   - `suites/low.yaml`
   - `suites/medium.yaml`
   - `suites/high.yaml`

6. Red-team and governance controls
   - `src/trusted_ai_toolkit/redteam/runner.py`
   - `src/tat/controls/scoring.py`
   - `src/tat/controls/library.py`

7. Scorecard generation
   - `src/trusted_ai_toolkit/reporting.py`
   - `src/trusted_ai_toolkit/templates/scorecard.html.j2`
   - `src/trusted_ai_toolkit/templates/scorecard.md.j2`

8. Explainability and lineage artifacts
   - `src/trusted_ai_toolkit/xai/reasoning_report.py`
   - `src/trusted_ai_toolkit/xai/lineage.py`
   - `src/trusted_ai_toolkit/templates/reasoning_report.md.j2`
   - `src/trusted_ai_toolkit/templates/lineage_report.md.j2`

9. Documentation artifacts
   - `src/trusted_ai_toolkit/documentation.py`
   - `src/trusted_ai_toolkit/templates/system_card.md.j2`
   - `src/trusted_ai_toolkit/templates/data_card.md.j2`
   - `src/trusted_ai_toolkit/templates/model_card.md.j2`
   - `src/trusted_ai_toolkit/templates/artifact_manifest.md.j2`

## Part 3: The Most Important Concept

Explain this very clearly:

`Answer trust is not the same as release approval.`

Use this breakdown:

- Answer trust asks:
  - is this answer supported by the available evidence?
  - are there contradictions?
  - should the user trust this answer?

- Governance status asks:
  - did the system pass release gates?
  - are there blocker findings?
  - are required artifacts complete?

Say this directly:

`A system can produce a grounded answer and still fail governance. It can also produce an untrusted answer even when the broader system controls are healthy.`

## Part 4: Scorecard Walkthrough

When the scorecard opens, explain each region in order:

1. Chips at the top
   - answer verdict
   - evidence completeness
   - configured risk
   - traceability
   - blocker findings
   - evidence confidence
   - template version marker

2. Main answer trust ring
   - user-facing confidence score for the answer
   - low score means the answer is weakly supported or contradicted

3. Side panel
   - deployment risk
   - control tier
   - answer verdict
   - release readiness

4. Bottom-line cards
   - bottom line
   - primary driver
   - next action

5. Expandable sections
   - answer checks
   - all evaluation metrics pass/fail table
   - traceability
   - security context
   - baseline trust inputs
   - governance flags

## Part 5: How to Explain the Metrics

Use this framing:

- deterministic metrics are the primary governance signals
- LLM judge metrics are advisory second opinions
- contradiction signals are safety-critical
- support and sufficiency signals show whether the answer is actually backed by the retrieved evidence

Key talking points:

- `claim_support_rate`
  - share of extracted claims supported by matched evidence

- `unsupported_claim_rate`
  - share of claims that are not supported

- `contradiction_rate`
  - share of claims that conflict with the retrieved evidence

- `evidence_sufficiency_score`
  - how complete the evidence support appears to be for the answer

- `context_relevance_embedding_coverage`
  - relevant chunks divided by total retrieved chunks

- `llm_contradiction_judge`
  - advisory semantic contradiction check using an LLM judge

- `llm_claim_entailment`
  - advisory semantic entailment check using an LLM judge

## Part 6: Artifact Story

Present artifact generation as four artifact families:

1. Runtime evidence
   - `prompt_run.json`
   - `eval_results.json`
   - `redteam_findings.json`
   - `redteam_summary.json`
   - `monitoring_summary.json`

2. Decision artifacts
   - `scorecard.json`
   - `scorecard.md`
   - `scorecard.html`

3. Explainability artifacts
   - `reasoning_report.md`
   - `reasoning_report.json`
   - `lineage_report.md`
   - `authoritative_data_index.json`

4. Documentation and audit artifacts
   - `system_card.md`
   - `data_card.md`
   - `model_card.md`
   - `artifact_manifest.json`
   - `artifact_manifest.md`
   - `incident_report.md` and `incident_report.json` when triggered

### Artifact Output Directory Reference

Default generated output location:

- `artifacts/<run_id>/`

Reference sample pack:

- `sample_evidence_pack/20260218T143752Z/`

Most important files to open live:

- `artifacts/<run_id>/scorecard.html`
- `artifacts/<run_id>/scorecard.json`
- `artifacts/<run_id>/eval_results.json`
- `artifacts/<run_id>/reasoning_report.md`
- `artifacts/<run_id>/artifact_manifest.json`

## Part 7: Suggested Live Demo Sequence

1. Show the app and ask a question
2. Show the returned answer in the UI
3. Open the scorecard
4. Expand `All Evaluation Metrics - Pass/Fail`
5. Point out:
   - passing metrics
   - failed metrics
   - advisory metrics
   - evidence completeness
   - stage gates
6. Open `Traceability`
7. Open `Baseline Trust Inputs`
8. Open the evidence pack folder or sample evidence pack
9. Show `reasoning_report.md`, `scorecard.json`, and `artifact_manifest.json`
10. Close by explaining how this supports audit, model risk, and release decisions

## Part 8: Close

Use this close:

`The key outcome is not just an answer. The key outcome is an answer with evidence, evaluation, red-team context, traceability, and a governance decision surface that can be reviewed by humans.`
