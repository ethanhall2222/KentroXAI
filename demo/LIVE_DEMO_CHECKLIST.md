# Live Demo Checklist

## Before the Demo

1. Confirm the repo is on latest `main`
   - `git log -1 --oneline`

2. Confirm Databricks app source is pointing at:
   - `apps/kentro-chat`

3. Confirm Databricks job source repo/workspace has latest code
   - `grep -R "scorecard-details-v2" -n src/trusted_ai_toolkit/templates/scorecard.html.j2`
   - `grep -R "llm_contradiction_judge" -n suites/rag_live.yaml`

Repo folders you may need to point at live:

- app: `apps/kentro-chat/`
- job entry: `rag_answer_trust_job.py`
- toolkit code: `src/trusted_ai_toolkit/`
- controls: `src/tat/`
- suites: `suites/`
- output artifacts: `artifacts/<run_id>/`

4. Reinstall editable package and restart Python in the notebook/job environment

```python
%pip install -e /Workspace/Users/ethan.hall@kentro.us/ts-rnd-explainable-ai --force-reinstall --no-deps
dbutils.library.restartPython()
```

5. Confirm the template marker is present in the next scorecard:
   - `Template scorecard-details-v2`

## Before Opening the UI

Clear old local browser session history if needed:

```js
localStorage.removeItem("kentro-chat-sessions")
location.reload()
```

## Recommended Demo Prompt Set

Use a sequence like this:

1. A straightforward question
   - `What is deep learning used for?`

2. A more governance-oriented question
   - `What controls should be reviewed before releasing an AI system?`

3. A deliberately weak or unsupported question
   - something outside the datasource scope to show a lower-trust outcome

## What to Verify in the UI

1. The answer returns
2. The trust score displays
3. The scorecard opens
4. The top chips show verdict, evidence completeness, configured risk, traceability, blocker findings, evidence confidence, and template version
5. `All Evaluation Metrics - Pass/Fail` is present
6. Expanding it reveals metric rows with:
   - metric name
   - value
   - threshold
   - status
   - strength
   - details

## What to Verify in the Evidence Pack

Check that the run folder contains:

- `prompt_run.json`
- `eval_results.json`
- `scorecard.json`
- `scorecard.html`
- `reasoning_report.md`
- `artifact_manifest.json`

## Recovery Steps if the Demo Looks Wrong

If the scorecard is missing recent UI changes:

1. pull latest repo in Databricks
2. reinstall editable package
3. restart Python
4. rerun the job from the top
5. redeploy or restart the Databricks app

If answer trust is obviously wrong:

1. inspect `eval_results.json`
2. inspect `scorecard.json`
3. compare `contradiction_rate`, `claim_support_rate`, `evidence_sufficiency_score`, and `output_support_*`
4. check whether the run is using the expected datasource and retrieved chunks

## Final Demo Close

End with this:

`What matters here is not only the answer. What matters is that the answer is accompanied by evidence, evaluation, traceability, and a governance decision package that can be reviewed by humans.`
