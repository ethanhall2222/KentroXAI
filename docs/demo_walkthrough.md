# Demo Ready Walkthrough

## Purpose
This walkthrough is designed for a 6 to 10 minute in-person review with technical stakeholders. Nothing needs to run live. Generate the bundle ahead of time, then present from the prebuilt evidence pack under `demo_outputs/latest/`.

The supplied `configs/demo_config.yaml` is already the fast deterministic path. It uses the existing toolkit CLI, a fixed prompt, a fixed model output, a fixed retrieved-context fixture, and a reduced red-team case list so the bundle is quick to regenerate while still showing threshold enforcement and stage-gate blocking.

## What Is Rigorous vs Heuristic vs Prototype
- Implemented rigor: Pydantic schema validation for config and system metadata, deterministic metric values, explicit threshold checks, stage-gate enforcement, shared `system_context` propagation, `system_hash` provenance, telemetry event capture, artifact manifest SHA-256 hashing, evidence completeness calculation.
- Heuristic logic: trust score weighting, card/display score penalties, 90% documentation completeness threshold for the documentation gate, anomaly flagging from telemetry counts.
- Prototype-level components: stub model output, offline eval metrics, deterministic string-triggered red-team cases, templated reasoning/lineage artifacts, placeholder context sources.

## Demo Sequence
Use `demo_outputs/latest/index.md` as the anchor and move in this exact order.

### A) Show `demo_config.yaml` sections (system + thresholds)
Open `configs/demo_config.yaml`.

What to highlight:
- `system` is a full `SystemSpec`, not an untyped blob. This is the provenance root.
- `eval.thresholds` is where pass/fail policy lives for metric gating.
- `redteam.cases` is intentionally small for fast repeatable prep, but still representative.
- `monitoring.enabled: true` guarantees a telemetry trail for the same run.
- The config is minimal on purpose; defaults handle the rest of the artifact policy.

Speaker notes:
- “This is the input contract. The system block is validated up front, and the same validated object feeds telemetry, scorecard provenance, and artifact payloads.”
- “Thresholds are policy, not UI logic. The scorecard only reflects what this config declares.”

### B) Show scorecard outcome and which thresholds triggered GO/NO-GO
Open `demo_outputs/latest/scorecard.json`.

What to highlight:
- `overall_status` and `go_no_go` are deterministic outputs.
- `stage_gate_status` shows exactly which gate blocked release.
- `required_actions` names the concrete blocker.
- `trust_score` is present, but it does not override a failed gate.
- `system_context.system_hash` ties the scorecard back to the validated `SystemSpec`.

Speaker notes:
- “The meeting headline is here: this demo bundle should land on `no-go` because the configured checks intentionally surface blocking evidence.”
- “Trust score is informative. Stage gates are authoritative.”

### C) Show `eval_results.json` metric payload
Open `demo_outputs/latest/eval_results.json`.

What to highlight:
- `system_context` is embedded directly in the artifact.
- Every metric includes `value`, `threshold`, and `passed`.
- The failing fairness metric is policy-visible, not buried in presentation code.
- Metric payloads are deterministic stub values, so the same config produces the same gate decision.

Speaker notes:
- “This is the machine-readable evidence behind the evaluation gate.”
- “In this demo, the fairness disparate impact ratio fails the configured threshold, so evaluation is a hard fail.”

### D) Show `redteam_findings.json` and pass/fail logic
Open `demo_outputs/latest/redteam_findings.json`.

What to highlight:
- Findings are per-case and include `severity`, `passed`, `evidence`, and `recommendation`.
- The demo prompt intentionally triggers high-severity failures.
- The config’s `severity_threshold: high` means those findings can escalate to blocking behavior and incident generation.
- `system_context` is carried here too for provenance consistency.

Speaker notes:
- “This is deterministic red-team logic. It is intentionally simple in this repo, but the enforcement path is real: findings become stage-gate inputs and incident triggers.”
- “The important distinction is that case execution is prototype-level, but the policy wiring from findings into governance is implemented.”

### E) Show telemetry / monitoring artifacts
Open `demo_outputs/latest/monitoring_summary.json`, then optionally `demo_outputs/latest/telemetry.jsonl`.

What to highlight:
- `monitoring_summary.json` is derived from emitted telemetry, not separately hand-authored.
- `events_by_type` and `events_by_component` show run traceability.
- `telemetry.jsonl` includes repeated `system_id` and `system_hash`, which proves run-level provenance consistency.
- Monitoring anomalies are heuristics; telemetry capture itself is implemented.

Speaker notes:
- “This gives me an audit trail without running anything live.”
- “If challenged on provenance, the `system_hash` in telemetry, eval, red-team, and scorecard should all line up.”

### F) Show `artifact_manifest.json` completeness and how it aligns
Open `demo_outputs/latest/artifact_manifest.json`.

What to highlight:
- Every file has a SHA-256 digest, size, and modified timestamp.
- `required_outputs` is the contract used for completeness scoring.
- `completeness` should match `scorecard.json -> evidence_completeness` exactly.
- This is the artifact integrity story: presence plus hashing plus completeness alignment.

Speaker notes:
- “Completeness is not guessed from the folder view. It is calculated against an explicit required-output list.”
- “For the demo, the manifest percentage and the scorecard percentage should match exactly. If they do not, that is a regression.”

### G) Show evidence pack folder structure
Open `demo_outputs/latest/` in your editor sidebar or file browser.

What to highlight:
- The bundle is self-contained for the meeting.
- `index.md` gives the ordered narrative.
- `_source/<run_id>/` preserves the original raw CLI output for traceability.
- The bundle root contains copied artifacts so you do not need to navigate the raw run directory live.

Speaker notes:
- “This is the presentable bundle. The `_source` directory is the forensic copy; the root is the curated meeting view.”

## Exact Click Order
1. `configs/demo_config.yaml`
2. `demo_outputs/latest/index.md`
3. `demo_outputs/latest/run_context.json`
4. `demo_outputs/latest/scorecard.json`
5. `demo_outputs/latest/eval_results.json`
6. `demo_outputs/latest/redteam_findings.json`
7. `demo_outputs/latest/monitoring_summary.json`
8. `demo_outputs/latest/artifact_manifest.json`
9. `demo_outputs/latest/` folder view

## If Asked (Short Answers)
- How is trust score derived?
  The scorecard computes pillar pass rates from deterministic control checks, blends red-team pass rate into the security pillar, then averages the four pillars equally.
- How is completeness calculated?
  The manifest compares files present in the run directory against `required_outputs` for the configured risk tier, then reports the percentage matched.
- What are the stage-gate override rules?
  A failed gate always forces `no-go`. A trust score cannot override it. Medium and high risk tiers require red-team, and medium/high block on high-severity red-team findings.
- Where do thresholds live?
  Metric thresholds live in `configs/demo_config.yaml` under `eval.thresholds`. Red-team severity policy lives under `redteam.severity_threshold`. Risk-gate rules live under `governance.risk_gate_rules`.

## Terminal Staging
Run these before the meeting:

```bash
./scripts/demo_prep.sh
export DEMO_DIR="$(python3 -c 'from pathlib import Path; print((Path("demo_outputs") / "latest").resolve())')"
printf '%s\n' "$DEMO_DIR"
ls "$DEMO_DIR"
```

Suggested terminal tabs:
1. Repo root: keep `./scripts/demo_prep.sh` and its last successful output visible.
2. Bundle root: `cd "$DEMO_DIR"` and keep `ls` output visible.
3. Proof tab: `sed -n '1,220p' "$DEMO_DIR/scorecard.json"` in case someone wants raw JSON without switching windows.

## Editor Tab Order
Open these ahead of time in this order:
1. `configs/demo_config.yaml`
2. `demo_outputs/latest/index.md`
3. `demo_outputs/latest/run_context.json`
4. `demo_outputs/latest/scorecard.json`
5. `demo_outputs/latest/eval_results.json`
6. `demo_outputs/latest/redteam_findings.json`
7. `demo_outputs/latest/monitoring_summary.json`
8. `demo_outputs/latest/artifact_manifest.json`

## Meeting-Day Checklist
- Regenerate the bundle once on the same machine you will present from.
- Confirm `demo_outputs/latest/` resolves and opens cleanly.
- Verify `scorecard.json` and `artifact_manifest.json` report the same completeness percentage.
- Verify `system_hash` matches across `run_context.json`, `scorecard.json`, `eval_results.json`, and `redteam_findings.json`.
- Pre-open the editor tabs in the order above.
- Keep the terminal on the already-generated bundle path; do not plan to execute commands live.
