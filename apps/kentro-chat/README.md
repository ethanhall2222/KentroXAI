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

## Project Layout

```text
apps/kentro-chat/
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
