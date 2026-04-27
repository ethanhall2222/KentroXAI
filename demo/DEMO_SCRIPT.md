# KentroXAI Demo Script

You can read it directly, trim it down, or paste it into Word as a presenter script.

---

## 1. Opening

### Ethan

`Thanks everyone. Today we are going to walk through the full KentroXAI lifecycle. The goal is to show that this is not just a chatbot returning an answer. It is a governed AI response flow that takes a question, evaluates the answer against evidence, runs governance checks, and generates a full evidence pack that can be reviewed later.`

### Jackson

`The important framing for this demo is that the output is not only the answer itself. The output is the answer plus the trust and governance context around that answer. That means evaluation, traceability, artifacts, and decision support for release and review.`

### Ethan

`We built a local demo kit for this walkthrough. The main files we will reference are in the demo folder. The browser-friendly overview is in demo/index.html, the walkthrough is in demo/DEMO_WALKTHROUGH.md, the artifact breakdown is in demo/ARTIFACT_GUIDE.md, and the live validation checklist is in demo/LIVE_DEMO_CHECKLIST.md.`

---

## 2. High-Level Architecture

### Ethan

`At a high level, this system has three layers.`

`First is the experience layer, which is the chat application under apps/kentro-chat. That is where the user asks the question, receives the answer, and opens the scorecard.`

`Second is the orchestration layer, which is the Databricks-backed execution path. That includes the job entry in rag_answer_trust_job.py and the CLI orchestration in src/trusted_ai_toolkit/cli.py. This layer takes the request and coordinates the rest of the lifecycle.`

`Third is the governance layer, which lives primarily in src/trusted_ai_toolkit. That includes evaluation, reporting, red-team, explainability, lineage, documentation, and artifact generation.`

### Jackson

`A simple way to think about it is this: the app is the front door, the Databricks job is the execution spine, and the toolkit is the governance engine.`

---

## 3. Repo and Directory Orientation

### Ethan

`Before we run anything, I want to ground the demo in the actual repo so it is clear where each part of the lifecycle lives.`

`The app lives in apps/kentro-chat.`

`The Databricks job entry point is rag_answer_trust_job.py.`

`The core toolkit package is under src/trusted_ai_toolkit.`

`The deterministic controls package is under src/tat.`

`The evaluation suites are defined under suites.`

`The rendering templates for the scorecard, reasoning report, cards, and manifest are under src/trusted_ai_toolkit/templates.`

`And every run writes its evidence pack under artifacts/<run_id>.`

### Jackson

`So when we say this is auditable, that is not abstract. There are actual directories and actual files for every major step of the lifecycle.`

---

## 4. What Happens End to End

### Ethan

`Now let’s walk through the runtime lifecycle.`

`Step one: the user asks a question in the Kentro chat app.`

`Step two: the backend hands that question off to the Databricks job flow.`

`Step three: the job retrieves evidence chunks, builds the prompt, and generates the answer.`

`Step four: the system writes runtime artifacts like prompt_run.json so we know exactly what was asked, what context was retrieved, and what answer was returned.`

`Step five: the evaluation engine runs. This is where answer-truth and support metrics get computed.`

`Step six: governance and security checks run, including control-based scoring and red-team summaries.`

`Step seven: explainability artifacts are generated, like the reasoning report and lineage outputs.`

`Step eight: the scorecard and documentation artifacts are rendered and written into the evidence pack.`

### Jackson

`So the key point is that one question kicks off a chain that ends in a full evidence package, not just a text response.`

---

## 5. Transition to the App

### Ethan

`Now I’m going to move into the app itself. The question we use here can be simple, because the value of the platform is not just in the answer. The value is in the governed lifecycle around the answer.`

`For example, I might ask: What is deep learning used for?`

### Jackson

`What we want the audience to pay attention to first is not whether the answer sounds polished. It is whether the platform can explain, evaluate, and govern that answer.`

---

## 6. Reviewing the Answer in the UI

### Ethan

`Here the app returns the answer in the chat interface. That chat experience is intentionally simple. The answer is shown first. Everything else is secondary and only becomes visible when needed.`

`From here, I can open the scorecard.`

### Jackson

`This is where the experience shifts from conversational output to governed output. The scorecard is the bridge between the end-user response and the internal evidence pack.`

---

## 7. Scorecard Overview

### Ethan

`At the top of the scorecard we have summary chips. These show things like answer verdict, evidence completeness, configured risk, traceability, blocker findings, and evidence confidence.`

`You may also see a template version marker. That marker is useful operationally because it tells us which scorecard template version actually rendered for the run.`

`The large trust ring is the answer trust score. This is user-facing confidence in the answer itself.`

`On the right side we separate answer verdict from release readiness. That separation is important.`

### Jackson

`This is one of the most important concepts in the whole demo: answer trust is not the same thing as release approval.`

`Answer trust asks whether the answer appears supported by evidence.`

`Release readiness asks whether the broader governed system passed its gates and controls.`

`A grounded answer can still fail governance. And a healthy governed system can still produce an answer that should not be trusted.`

---

## 8. Bottom-Line Panels

### Ethan

`The next area is the bottom-line summary. We have a bottom line, a primary driver, and a next action.`

`These sections are there to make the result interpretable quickly.`

`If the answer is weak, the primary driver tells us why. If the system is blocked, the next action tells us what to do next.`

### Jackson

`This is critical for real operations. A score alone is not useful. The system has to explain the cause and point to the remediation path.`

---

## 9. Expandable Sections

### Ethan

`Below that, the scorecard shifts into deeper detail. Everything here is expandable and collapsed by default so the default experience stays clean.`

`The first expandable section is Answer Checks.`

`That gives the direct reasons the answer landed in its current verdict.`

`The next section is All Evaluation Metrics - Pass/Fail.`

`This is one of the most important sections in the live demo, because it shows every metric that ran, the value, the threshold, whether it passed or failed, how strong the metric is, and extra details about the metric.`

### Jackson

`This is where you move from summary into proof.`

`Instead of saying the system thought something was wrong, we can show exactly which metrics passed, which failed, and what evidence or reasoning supported that conclusion.`

---

## 10. Explaining the Metrics

### Ethan

`Let me call out a few important metrics.`

`Claim support rate is the share of extracted claims that appear supported by matched evidence.`

`Unsupported claim rate is the share that do not appear supported.`

`Contradiction rate is the share of claims that appear to conflict with the evidence.`

`Evidence sufficiency score estimates how complete the evidence support is for the answer.`

`Context relevance embedding coverage measures relevant chunks divided by total retrieved chunks, which helps us understand how much of the retrieval set was actually useful.`

`We also have advisory LLM judge metrics, including llm_contradiction_judge and llm_claim_entailment. Those are second-opinion semantic judges, not the hard gating signals.`

### Jackson

`This is a good place to make an audience distinction.`

`The deterministic metrics are the main governance signals.`

`The LLM judge metrics are advisory.`

`That means they add interpretability and a second semantic lens, but they do not silently override the core release logic.`

---

## 11. Traceability and Security Context

### Ethan

`The next expandable area is Traceability.`

`This shows the run ID, system, environment, and traceability status. This is what lets us tie a scorecard back to a specific governed run and system context.`

`Then we have Security Context.`

`That summarizes blocker thresholds, findings, and evaluation counts.`

### Jackson

`This matters because trust without traceability is not governance.`

`And trust without security context is not operationally useful.`

---

## 12. Baseline Trust Inputs

### Ethan

`Next is Baseline Trust Inputs.`

`This breaks down how control-backed governance scoring contributes to the system view.`

`We can expand each pillar, such as security, reliability, transparency, and governance, to see how its score was formed and how much it contributes.`

### Jackson

`This helps answer the question, what is underneath the headline score?`

`It shows that the platform is not just inventing a trust number. It is assembling that number from explicit policy and control categories.`

---

## 13. Governance Flags

### Ethan

`Finally, Governance Flags summarizes the release-side decision.`

`This includes decision status, release decision, stage gates, and any required actions or blocker interpretation.`

### Jackson

`This is the release-facing layer of the demo.`

`This is where an engineering lead, governance reviewer, or release owner can answer: are we good to proceed, or do we need remediation first?`

---

## 14. Transition to the Evidence Pack

### Ethan

`Now that we’ve seen the scorecard in the app, I want to show the evidence pack itself. The app is only one view. The real output of the system is the set of artifacts written under artifacts/<run_id>.`

### Jackson

`This is where the platform becomes auditable. The evidence pack is what lets someone review the run after the fact rather than only trusting a live UI.`

---

## 15. Artifact Walkthrough

### Ethan

`The first file I usually show is prompt_run.json.`

`That proves what was asked, what context was retrieved, and what answer was returned.`

`Then I show eval_results.json.`

`That contains the metric outputs that drove the answer evaluation layer.`

`Then I show scorecard.json.`

`That is the structured machine-readable summary of the scorecard, including verdicts, metrics, stage gates, and actions.`

`Then I show scorecard.html.`

`That is the human-friendly interactive card we just viewed in the app.`

`Next I show reasoning_report.md and lineage_report.md.`

`These explain how the answer was interpreted and what sources or context it was tied to.`

`Finally I show artifact_manifest.json.`

`This is the proof that the evidence package itself is a managed output and not just a set of ad hoc files.`

### Jackson

`For a live audience, I would frame these in four families: runtime evidence, decision artifacts, explainability artifacts, and documentation or audit artifacts.`

---

## 16. Mapping Artifacts to Audiences

### Ethan

`Different artifacts serve different audiences.`

`Engineers care about prompt_run.json, eval_results.json, and scorecard.json.`

`Governance reviewers care about scorecard.html, reasoning_report.md, and the manifest.`

`Security stakeholders care about redteam_findings.json and redteam_summary.json.`

`Operations teams care about monitoring_summary.json, telemetry.jsonl, and incident artifacts if escalation occurs.`

### Jackson

`This is why the system is useful across the lifecycle. It is not a single report built for a single audience. It is a structured package built for multiple review layers.`

---

## 17. How to Explain the Sample Evidence Pack

### Ethan

`If we want a stable non-live example, we also keep a sample evidence pack in sample_evidence_pack/20260218T143752Z.`

`That gives us a reliable walkthrough target even when we are not running a fresh live question.`

### Jackson

`That is useful for rehearsals, stakeholder previews, and situations where you want to walk the artifacts without relying on a fresh runtime execution.`

---

## 18. Closing Message

### Ethan

`To close, the key thing I want to emphasize is that KentroXAI is not only an answer system. It is an answer governance system.`

`The value is that every answer can be paired with evidence, evaluation, traceability, security context, documentation, and a human-reviewable decision surface.`

### Jackson

`The practical outcome is that teams do not have to choose between speed and governance. They can get an answer quickly, while still generating the artifact trail required for trust, review, and release decisions.`

---

## 19. Optional Q&A Short Answers

### If someone asks: “What is the main output?”

### Jackson

`The main output is the evidence-backed governance package. The visible answer is only one part of it.`

### If someone asks: “What proves this is auditable?”

### Ethan

`The run folder under artifacts/<run_id> contains the underlying prompt, evaluation, scorecard, reports, traceability outputs, and manifest.`

### If someone asks: “What is the difference between trust and release readiness?”

### Jackson

`Trust is answer-level. Release readiness is system-level. They inform each other, but they are not the same decision.`

### If someone asks: “Where do the decisions come from in the code?”

### Ethan

`The main sources are src/trusted_ai_toolkit/eval/runner.py for metric execution, src/trusted_ai_toolkit/eval/metrics for metric definitions, src/trusted_ai_toolkit/reporting.py for scorecard logic, and src/tat/controls for the control-backed governance scoring.`
