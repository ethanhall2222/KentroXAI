# Databricks Integration

This repository can run on Databricks as a Python wheel job. The recommended shape is:

- package the repo as a wheel
- deploy it with Databricks Asset Bundles
- store config, context, and output artifacts in a Unity Catalog volume
- keep provider credentials in Databricks secrets

## What this repo now includes

- a Databricks-friendly wheel entrypoint in `src/trusted_ai_toolkit/jobs.py`
- a reusable Databricks backend helper in `src/trusted_ai_toolkit/databricks_pipeline.py`
- a sample bundle in `databricks.yml`
- a sample Databricks job resource in `resources/trusted_ai_toolkit_job.yml`
- support for wheel-task keyword arguments and `TAT_*` environment variables

## Job entrypoint

The wheel task entrypoint is:

- package name: `trusted_ai_toolkit`
- entry point: `tat-databricks-job`

It supports both Databricks wheel keyword arguments and environment variables.

Supported keyword arguments:

- `config`
- `prompt`
- `context_file`
- `mode`
- `model_output`
- `provider`
- `endpoint`
- `model`
- `api_key_env`
- `request_format`

Supported environment variables:

- `TAT_CONFIG_PATH`
- `TAT_PROMPT`
- `TAT_CONTEXT_FILE`
- `TAT_MODEL_OUTPUT`
- `TAT_JOB_MODE`
- `TAT_OUTPUT_DIR`
- `TAT_RUN_ID`
- `TAT_ADAPTER_PROVIDER`
- `TAT_ADAPTER_ENDPOINT`
- `TAT_ADAPTER_MODEL`
- `TAT_ADAPTER_API_KEY_ENV`
- `TAT_ADAPTER_REQUEST_FORMAT`

`mode` supports:

- `prompt`
- `simulate`

## Recommended Unity Catalog layout

Use a Unity Catalog volume for toolkit files:

- config: `/Volumes/<catalog>/<schema>/<volume>/configs/config.yaml`
- contexts: `/Volumes/<catalog>/<schema>/<volume>/contexts/<run>.json`
- artifacts: `/Volumes/<catalog>/<schema>/<volume>/artifacts/`

Example variable values for the sample bundle:

- `config_path`: `/Volumes/main/ai_governance/trusted_ai_toolkit/configs/config.yaml`
- `context_file`: `/Volumes/main/ai_governance/trusted_ai_toolkit/contexts/policy_context.json`
- `output_dir`: `/Volumes/main/ai_governance/trusted_ai_toolkit/artifacts`

## Secret management

For hosted-model runs, store the provider key in a Databricks secret scope and map it to `OPENAI_API_KEY` through `spark_env_vars`.

The sample bundle assumes:

- scope: `ai-secrets`
- key: `openai-api-key`

Update `openai_api_key_secret_scope` and `openai_api_key_secret_key` if your names differ.

## Deployment flow

1. Configure Databricks CLI authentication.
2. Set the bundle variables for your workspace, cluster, and volume paths.
3. Validate the bundle:

```bash
databricks bundle validate
```

4. Deploy the bundle:

```bash
databricks bundle deploy
```

5. Run the job:

```bash
databricks bundle run trusted_ai_toolkit_job
```

## Example prompt-mode run

Set bundle variables so the job receives:

- `mode=prompt`
- `config=/Volumes/.../configs/config.yaml`
- `prompt=Summarize the governance posture`
- `context_file=/Volumes/.../contexts/policy_context.json`
- `output_dir=/Volumes/.../artifacts`

This executes the same flow as:

```bash
tat run prompt --config /Volumes/.../configs/config.yaml --prompt "Summarize the governance posture" --context-file /Volumes/.../contexts/policy_context.json
```

## Example simulate-mode run

Set bundle variables so the job receives:

- `mode=simulate`
- `provider=openai_compatible`
- `endpoint=https://api.openai.com/v1`
- `model=gpt-4.1-mini`
- `api_key_env=OPENAI_API_KEY`
- `request_format=responses`

This executes the same governance pipeline but obtains model output from the configured provider before building artifacts.

## Notes

- The sample bundle uses an existing cluster to stay cloud-agnostic.
- The toolkit still writes file-based artifacts. Databricks integration here is focused on operationalizing the current architecture, not replacing it with notebooks.
- If you want dashboarding, the next logical step is to add a post-run task that loads `scorecard.json`, `monitoring_summary.json`, and `eval_results.json` into Delta tables.

## Databricks UI / RAG backend pattern

For a Databricks-hosted chat UI, the recommended split is:

1. Databricks retrieval code queries the existing RAG tables and returns the exact chunks used for answer generation.
2. OpenAI generates the answer from those chunks.
3. `trusted_ai_toolkit.databricks_pipeline.run_databricks_answer_pipeline(...)` turns the question, answer, and chunks into Kentro artifacts and a scorecard.
4. The UI stores a compact run summary in Delta for history and monitoring.

The backend helper intentionally expects Databricks to own retrieval and generation. Kentro stays responsible for:

- `prompt_run.json`
- `eval_results.json`
- `scorecard.json`
- `scorecard.html`
- benchmark updates

### Suggested Delta log columns

If you want the UI and backend job to preserve the live answer and source bundle, extend the run-log table with:

```sql
ALTER TABLE <catalog>.<schema>.kentroxai_governance_runs
ADD COLUMNS (
  answer_text STRING,
  retrieved_chunks_json STRING
);
```

`build_governance_run_row(...)` in `databricks_pipeline.py` returns a Delta-friendly summary row with those fields included.
