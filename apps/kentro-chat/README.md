# Kentro Chat

`apps/kentro-chat` is a companion app that lets Kentro's chat product live alongside the existing Python governance engine instead of replacing it.

It includes:

- a React frontend with a ChatGPT-style dark workspace
- a Node/Express backend with `POST /api/chat`
- an optional backend hook that can call Kentro's existing Python CLI after each reply to generate governance artifacts

## Local Run

From the repo root:

```bash
cd apps/kentro-chat
npm install
npm run dev
```

That starts:

- frontend at `http://localhost:5173`
- backend at `http://localhost:5050`

The Vite dev server proxies `/api/*` calls to the Express backend.

## Databricks Apps Deploy

To deploy this as a Databricks App, point the app source at:

```text
apps/kentro-chat
```

This folder is now packaged as a single deployable Node app:

- `npm run build` builds the React frontend into `frontend/dist`
- `npm run start` starts Express
- Express serves both `/api/*` and the built frontend bundle
- the server automatically listens on `DATABRICKS_APP_PORT` when running inside Databricks Apps

Required setup notes:

- Do not point Databricks at the broader repo root unless you add separate root-level app packaging.
- If you deploy from a workspace folder, make sure the selected folder is `apps/kentro-chat` itself.
- If you want the governance hook enabled in Databricks, add the same env vars from `backend/.env.example` in the Databricks app Environment tab.

## Project Layout

```text
apps/kentro-chat/
  app.yaml
  backend/
  frontend/
  package.json
  README.md
```

## Backend Chat API

The scaffold exposes:

```bash
POST /api/chat
Content-Type: application/json
```

Request shape:

```json
{
  "message": "What changed in the latest policy review?",
  "history": [
    { "role": "user", "content": "Summarize our deployment posture." }
  ]
}
```

Response shape:

```json
{
  "reply": "Scaffolded assistant response...",
  "model": "local-scaffold",
  "governance": {
    "enabled": false,
    "attempted": false
  }
}
```

## Kentro Governance Handoff

By default, chat responses stay local to the Node backend and do not invoke the Python toolkit.

To trigger governance artifacts after each assistant reply, create `apps/kentro-chat/backend/.env`:

```bash
PORT=5050
FRONTEND_ORIGIN=http://localhost:5173
KENTRO_CHAT_MODEL=local-scaffold
KENTRO_ENABLE_GOVERNANCE_HOOK=true
KENTRO_CLI_BIN=tat
KENTRO_CLI_ARGS=
KENTRO_CONFIG_PATH=../../../config.yaml
KENTRO_CONTEXT_FILE=
```

When enabled, the backend will execute:

```bash
tat run prompt --config ../../../config.yaml --prompt "<user message>" --model-output "<assistant reply>"
```

Useful alternatives:

- If `tat` is installed in the environment, keep `KENTRO_CLI_BIN=tat`.
- If the repo is only available as source, set `KENTRO_CLI_BIN=python` and `KENTRO_CLI_ARGS=-m trusted_ai_toolkit.cli`.
- If you want a different config, point `KENTRO_CONFIG_PATH` at another Kentro YAML file.
- If you already have retrieved context in JSON form, point `KENTRO_CONTEXT_FILE` at that file and it will be forwarded to the CLI.

The chat API still returns a reply even if the governance hook fails. Hook status is included in the JSON response so the UI can surface the result without turning routine chat into a hard failure.

## Databricks Job Backend (Option A)

This app can also hand off each question to a Databricks Job instead of
running the local CLI hook. In this mode the backend:

1. generates a `request_id`
2. calls `jobs/run-now` with `question` and `request_id`
3. waits for the Databricks job to finish
4. queries the governance Delta table by `request_id`
5. returns the final answer plus trust-card summary to the frontend

Enable it by setting these backend env vars:

```bash
KENTRO_ENABLE_DATABRICKS_JOB_BACKEND=true
DATABRICKS_HOST=https://<your-workspace-host>
DATABRICKS_TOKEN=<token-with-job-and-sql-access>
KENTRO_DATABRICKS_JOB_ID=<job-id>
KENTRO_SQL_WAREHOUSE_ID=<sql-warehouse-id>
KENTRO_GOVERNANCE_TABLE=wvu.ethanhall.kentroxai_governance_runs
KENTRO_JOB_POLL_INTERVAL_MS=3000
KENTRO_JOB_TIMEOUT_MS=120000
```

The Databricks job notebook must accept these widgets:

```python
dbutils.widgets.text("question", "")
dbutils.widgets.text("request_id", "")
```

and persist `request_id` into the governance Delta table.
