import cors from "cors";
import dotenv from "dotenv";
import express from "express";
import OpenAI from "openai";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const app = express();

const PORT = Number.parseInt(process.env.PORT ?? process.env.DATABRICKS_APP_PORT ?? "5050", 10);
const FRONTEND_ORIGIN = process.env.FRONTEND_ORIGIN ?? "http://localhost:5173";
const CHAT_MODEL = process.env.KENTRO_CHAT_MODEL ?? "gpt-4.1-mini";
const DATABRICKS_HOST = (process.env.DATABRICKS_HOST ?? "").replace(/\/$/, "");
const DATABRICKS_CLIENT_ID = process.env.DATABRICKS_CLIENT_ID ?? "";
const DATABRICKS_CLIENT_SECRET = process.env.DATABRICKS_CLIENT_SECRET ?? "";
const DATABRICKS_JOB_ID = process.env.KENTRO_DATABRICKS_JOB_ID ?? "";
const JOB_POLL_INTERVAL_MS = Number.parseInt(process.env.KENTRO_JOB_POLL_INTERVAL_MS ?? "3000", 10);
const JOB_TIMEOUT_MS = Number.parseInt(process.env.KENTRO_JOB_TIMEOUT_MS ?? "600000", 10);

let databricksAccessTokenCache = {
  token: "",
  expiresAtMs: 0,
};

const repoRoot = path.resolve(__dirname, "../../..");
const defaultConfigPath = path.resolve(__dirname, "../../../config.yaml");
const frontendDistDir = path.resolve(__dirname, "../frontend/dist");
const frontendIndexPath = path.join(frontendDistDir, "index.html");
const servingBundledFrontend = fs.existsSync(frontendIndexPath);

app.use(cors({ origin: servingBundledFrontend ? true : FRONTEND_ORIGIN }));
app.use(express.json({ limit: "1mb" }));

app.get("/api/health", (_req, res) => {
  const liveModelReady = hasLiveModelAccess();

  res.json({
    ok: true,
    service: "kentro-chat-backend",
    repoRoot,
    model: liveModelReady ? CHAT_MODEL : "local-scaffold",
    liveModelReady,
    governanceHookEnabled: isGovernanceHookEnabled(),
    jobBackendEnabled: isJobBackendEnabled(),
    databricksHostConfigured: Boolean(DATABRICKS_HOST),
    databricksClientIdConfigured: Boolean(DATABRICKS_CLIENT_ID),
    databricksJobIdConfigured: Boolean(DATABRICKS_JOB_ID),
    sessionMode: isJobBackendEnabled()
      ? "databricks-job"
      : isGovernanceHookEnabled()
        ? "governance-enabled"
        : "local-chat",
  });
});

app.get("/api/scorecard", (req, res) => {
  const artifactPath = typeof req.query.artifactPath === "string" ? req.query.artifactPath : "";

  if (!artifactPath) {
    res.status(400).json({ error: "An `artifactPath` query value is required." });
    return;
  }

  try {
    const scorecardHtmlPath = resolveScorecardHtmlPath(artifactPath);
    res.sendFile(scorecardHtmlPath);
  } catch (error) {
    res.status(404).json({
      error: error instanceof Error ? error.message : "Unable to locate scorecard output.",
    });
  }
});

app.post("/api/chat", async (req, res) => {
  const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";
  const history = Array.isArray(req.body?.history) ? req.body.history : [];

  if (!message) {
    res.status(400).json({ error: "A non-empty `message` field is required." });
    return;
  }

  if (isJobBackendEnabled()) {
    try {
      const requestId = randomUUID();
      const governance = await runDatabricksJobBackend({ message, requestId });
      res.json({
        reply: governance.answerText || "No answer returned from Databricks.",
        model: governance.model ?? CHAT_MODEL,
        governance,
      });
      return;
    } catch (error) {
      console.error("Databricks job backend failed:", error);
      res.status(502).json({
        error: error instanceof Error ? error.message : String(error),
        details:
          error && typeof error === "object" && "details" in error && typeof error.details === "string"
            ? error.details
            : "",
      });
      return;
    }
  }

  try {
    const completion = await generateReply(message, history);
    const governance = await maybeRunGovernanceHook({ message, reply: completion.reply });

    res.json({
      reply: completion.reply,
      model: completion.model,
      governance,
    });
  } catch (error) {
    console.error("Chat request failed:", error);

    res.status(500).json({
      error: error instanceof Error ? error.message : "OpenAI request failed",
    });
  }
});

if (servingBundledFrontend) {
  app.use(express.static(frontendDistDir));

  app.get("*", (req, res, next) => {
    if (req.path.startsWith("/api/")) {
      next();
      return;
    }

    res.sendFile(frontendIndexPath);
  });
}

app.listen(PORT, () => {
  console.log(
    `Kentro chat backend listening on http://localhost:${PORT}${servingBundledFrontend ? " and serving frontend bundle" : ""}`,
  );
});

async function generateReply(message, history) {
  const apiKey = process.env.OPENAI_API_KEY || process.env.openai_secret;

  if (!apiKey) {
    return {
      reply: buildScaffoldReply(message, history),
      model: "local-scaffold",
    };
  }

  const openai = new OpenAI({ apiKey });
  const input = [
    ...history
      .filter((entry) => entry && typeof entry.role === "string" && typeof entry.content === "string")
      .map((entry) => ({
        role: entry.role,
        content: entry.content,
      })),
    {
      role: "user",
      content: message,
    },
  ];

  const response = await openai.responses.create({
    model: CHAT_MODEL,
    input,
  });

  return {
    reply: response.output_text || "No reply returned from OpenAI.",
    model: CHAT_MODEL,
  };
}

function buildScaffoldReply(message, history) {
  const normalized = message.replace(/\s+/g, " ").trim();
  const priorTurns = history.filter((entry) => entry && typeof entry.content === "string").length;

  const responseParts = [
    "This is the Kentro chat scaffold speaking through the local Express API.",
    `I received: "${normalized}"`,
    priorTurns > 0
      ? `I can also see ${priorTurns} earlier message${priorTurns === 1 ? "" : "s"} in the conversation context.`
      : "This looks like the first turn in the current conversation.",
    "Once a real model is connected, this endpoint can swap the stubbed reply for live output without changing the frontend contract.",
  ];

  return responseParts.join(" ");
}

function hasLiveModelAccess() {
  return Boolean(process.env.OPENAI_API_KEY || process.env.openai_secret);
}

function isJobBackendEnabled() {
  return String(process.env.KENTRO_ENABLE_DATABRICKS_JOB_BACKEND ?? "").toLowerCase() === "true";
}

function isGovernanceHookEnabled() {
  return String(process.env.KENTRO_ENABLE_GOVERNANCE_HOOK ?? "").toLowerCase() === "true";
}

function requireDatabricksBackendConfig() {
  const missing = [];
  if (!DATABRICKS_HOST) missing.push("DATABRICKS_HOST");
  if (!DATABRICKS_CLIENT_ID) missing.push("DATABRICKS_CLIENT_ID");
  if (!DATABRICKS_CLIENT_SECRET) missing.push("DATABRICKS_CLIENT_SECRET");
  if (!DATABRICKS_JOB_ID) missing.push("KENTRO_DATABRICKS_JOB_ID");
  if (missing.length > 0) {
    throw new Error(`Databricks job backend is missing required env vars: ${missing.join(", ")}`);
  }
}

async function getDatabricksAccessToken() {
  const now = Date.now();

  if (databricksAccessTokenCache.token && databricksAccessTokenCache.expiresAtMs - 60_000 > now) {
    return databricksAccessTokenCache.token;
  }

  const tokenUrl = `${DATABRICKS_HOST}/oidc/v1/token`;
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    scope: "all-apis",
  });

  const basicAuth = Buffer.from(
    `${DATABRICKS_CLIENT_ID}:${DATABRICKS_CLIENT_SECRET}`,
    "utf8",
  ).toString("base64");

  const response = await fetch(tokenUrl, {
    method: "POST",
    headers: {
      Authorization: `Basic ${basicAuth}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Databricks OAuth token request failed with ${response.status}: ${text}`);
  }

  const payload = await response.json();
  const accessToken = payload.access_token ?? "";
  const expiresIn = Number(payload.expires_in ?? 3600);

  if (!accessToken) {
    throw new Error("Databricks OAuth token response did not include access_token.");
  }

  databricksAccessTokenCache = {
    token: accessToken,
    expiresAtMs: now + expiresIn * 1000,
  };

  return accessToken;
}

async function databricksApi(pathname, init = {}) {
  const accessToken = await getDatabricksAccessToken();

  const response = await fetch(`${DATABRICKS_HOST}${pathname}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Databricks API ${pathname} failed with ${response.status}: ${body}`);
  }

  return response.json();
}

async function submitDatabricksRun({ message, requestId }) {
  return databricksApi("/api/2.1/jobs/run-now", {
    method: "POST",
    body: JSON.stringify({
      job_id: Number.parseInt(DATABRICKS_JOB_ID, 10),
      notebook_params: {
        question: message,
        request_id: requestId,
      },
    }),
  });
}

async function waitForRunCompletion(runId) {
  const startedAt = Date.now();
  let lastPayload = null;

  while (Date.now() - startedAt < JOB_TIMEOUT_MS) {
    const payload = await databricksApi(`/api/2.1/jobs/runs/get?run_id=${runId}`);
    lastPayload = payload;
    const state = payload.state ?? {};
    const lifeCycleState = state.life_cycle_state ?? "";
    const resultState = state.result_state ?? "";

    if (lifeCycleState === "TERMINATED") {
      if (resultState !== "SUCCESS") {
        throw await buildDatabricksRunError(
          payload,
          `Databricks job run ${runId} finished with ${resultState || "UNKNOWN"}: ${state.state_message ?? ""}`.trim(),
        );
      }
      return payload;
    }

    if (lifeCycleState === "INTERNAL_ERROR" || lifeCycleState === "SKIPPED") {
      throw await buildDatabricksRunError(
        payload,
        `Databricks job run ${runId} failed in state ${lifeCycleState}: ${state.state_message ?? ""}`.trim(),
      );
    }

    await sleep(JOB_POLL_INTERVAL_MS);
  }

  throw await buildDatabricksRunError(
    lastPayload,
    `Timed out waiting for Databricks job run ${runId}`,
  );
}

function getTaskRunId(runPayload) {
  const task = Array.isArray(runPayload.tasks) ? runPayload.tasks[0] : null;
  const taskRunId = task?.run_id;

  if (!taskRunId) {
    throw new Error("Databricks run completed but no task run_id was found in the run payload.");
  }

  return taskRunId;
}

function maybeTaskRunId(runPayload) {
  const task = Array.isArray(runPayload?.tasks) ? runPayload.tasks[0] : null;
  return task?.run_id ? String(task.run_id) : "";
}

async function getRunOutputPayload(taskRunId) {
  return databricksApi(`/api/2.1/jobs/runs/get-output?run_id=${taskRunId}`, {
    method: "GET",
  });
}

async function getRunOutput(taskRunId) {
  const payload = await getRunOutputPayload(taskRunId);

  const rawResult = payload.notebook_output?.result ?? "";

  if (!rawResult) {
    throw new Error(`Databricks task run ${taskRunId} completed but notebook output was empty.`);
  }

  try {
    return JSON.parse(rawResult);
  } catch (error) {
    throw new Error(
      `Databricks task run ${taskRunId} returned non-JSON notebook output: ${rawResult.slice(0, 500)}`
    );
  }
}

function compactDetail(value) {
  if (typeof value !== "string") {
    return "";
  }

  return value.trim();
}

function makeDatabricksError(message, details) {
  const error = new Error(message);
  error.details = details;
  return error;
}

async function buildDatabricksRunError(runPayload, fallbackMessage) {
  const state = runPayload?.state ?? {};
  const task = Array.isArray(runPayload?.tasks) ? runPayload.tasks[0] : null;
  const taskRunId = maybeTaskRunId(runPayload);
  const detailLines = [];
  let taskOutput = null;

  detailLines.push(`Run ID: ${runPayload?.run_id ?? "unknown"}`);
  if (taskRunId) {
    detailLines.push(`Task run ID: ${taskRunId}`);
  }
  if (state.life_cycle_state || state.result_state || state.state_message) {
    detailLines.push(
      `Run state: ${state.life_cycle_state || "UNKNOWN"} / ${state.result_state || "UNKNOWN"}${state.state_message ? ` - ${state.state_message}` : ""}`,
    );
  }
  if (task?.task_key) {
    detailLines.push(`Task key: ${task.task_key}`);
  }
  if (task?.state) {
    detailLines.push(
      `Task state: ${task.state.life_cycle_state || "UNKNOWN"} / ${task.state.result_state || "UNKNOWN"}${task.state.state_message ? ` - ${task.state.state_message}` : ""}`,
    );
  }

  if (taskRunId) {
    try {
      taskOutput = await getRunOutputPayload(taskRunId);
    } catch (error) {
      const apiFailure = error instanceof Error ? error.message : String(error);
      detailLines.push(`Task output lookup failed: ${apiFailure}`);
    }
  }

  const outputError = compactDetail(taskOutput?.error);
  const outputTrace = compactDetail(taskOutput?.error_trace);
  const notebookResult = compactDetail(taskOutput?.notebook_output?.result);
  const taskStateMessage = compactDetail(taskOutput?.metadata?.state?.state_message);
  const summaryReason = outputError || taskStateMessage || state.state_message || "";
  const summary = summaryReason ? `${fallbackMessage}\nCause: ${summaryReason}` : fallbackMessage;

  if (outputError) {
    detailLines.push("");
    detailLines.push("Databricks error:");
    detailLines.push(outputError);
  }
  if (outputTrace) {
    detailLines.push("");
    detailLines.push("Error trace:");
    detailLines.push(outputTrace);
  }
  if (notebookResult) {
    detailLines.push("");
    detailLines.push("Notebook output:");
    detailLines.push(notebookResult);
  }

  return makeDatabricksError(summary, detailLines.join("\n"));
}

async function runDatabricksJobBackend({ message, requestId }) {
  requireDatabricksBackendConfig();

  const runPayload = await submitDatabricksRun({ message, requestId });
  const parentRunId = runPayload.run_id;
  const completedRunPayload = await waitForRunCompletion(parentRunId);
  const taskRunId = getTaskRunId(completedRunPayload);
  const output = await getRunOutput(taskRunId);
  const scorecard = normalizeScorecardPayload(output.scorecard);

  return {
    enabled: true,
    attempted: true,
    success: true,
    mode: "databricks-job",
    requestId: output.request_id ?? requestId,
    databricksRunId: String(parentRunId),
    databricksTaskRunId: String(taskRunId),
    answerText: output.answer ?? "",
    answerVerdict: scorecard?.answer_verdict ?? scorecard?.answerVerdict ?? "",
    answerTrustScore: scorecard?.answerTrustScore ?? null,
    overallStatus: scorecard?.overallStatus ?? "",
    goNoGo: scorecard?.goNoGo ?? "",
    topDocUris: Array.isArray(output.retrieved_chunks)
      ? output.retrieved_chunks.map((chunk) => chunk.doc_uri).filter(Boolean)
      : [],
    retrievedChunksJson: JSON.stringify(output.retrieved_chunks ?? []),
    artifactPath: output.run_dir ?? "",
    artifactRunId: output.scorecard?.run_id ?? "",
    scorecardJsonPath: output.scorecard_json_path ?? "",
    scorecardHtml: output.scorecard_html ?? "",
    model: CHAT_MODEL,
    scorecard,
  };

}

async function maybeRunGovernanceHook({ message, reply }) {
  if (!isGovernanceHookEnabled()) {
    return {
      enabled: false,
      attempted: false,
    };
  }

  const cliBin = process.env.KENTRO_CLI_BIN?.trim() || "tat";
  const cliArgs = parseCliArgs(process.env.KENTRO_CLI_ARGS);
  const configPath = resolveFromBackend(process.env.KENTRO_CONFIG_PATH || defaultConfigPath);
  const contextFile = process.env.KENTRO_CONTEXT_FILE?.trim()
    ? resolveFromBackend(process.env.KENTRO_CONTEXT_FILE)
    : "";

  const commandArgs = [
    ...cliArgs,
    "run",
    "prompt",
    "--config",
    configPath,
    "--prompt",
    message,
    "--model-output",
    reply,
  ];

  if (contextFile) {
    commandArgs.push("--context-file", contextFile);
  }

  try {
    const result = await runCommand(cliBin, commandArgs, repoRoot);
    const artifactPath = extractArtifactPath(result.stdout);
    const scorecard = buildScorecardPayload(artifactPath);
    return {
      enabled: true,
      attempted: true,
      success: result.exitCode === 0,
      exitCode: result.exitCode,
      command: [cliBin, ...commandArgs].join(" "),
      artifactPath,
      artifactRunId: artifactPath ? path.basename(artifactPath) : "",
      scorecard,
      stdout: result.stdout.trim(),
      stderr: result.stderr.trim(),
    };
  } catch (error) {
    return {
      enabled: true,
      attempted: true,
      success: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function buildScorecardPayload(artifactPath) {
  if (!artifactPath) {
    return null;
  }

  const resolvedRunDir = resolveFromBackend(artifactPath);
  const scorecardJsonPath = path.join(resolvedRunDir, "scorecard.json");
  const scorecardHtmlPath = path.join(resolvedRunDir, "scorecard.html");

  if (!fs.existsSync(scorecardJsonPath) && !fs.existsSync(scorecardHtmlPath)) {
    return null;
  }

  let raw = null;
  if (fs.existsSync(scorecardJsonPath)) {
    try {
      raw = JSON.parse(fs.readFileSync(scorecardJsonPath, "utf8"));
    } catch (error) {
      console.error("Unable to parse scorecard.json:", error);
    }
  }

  return {
    artifactPath: resolvedRunDir,
    htmlPath: fs.existsSync(scorecardHtmlPath) ? scorecardHtmlPath : "",
    htmlUrl: fs.existsSync(scorecardHtmlPath)
      ? `/api/scorecard?artifactPath=${encodeURIComponent(resolvedRunDir)}`
      : "",
    jsonPath: fs.existsSync(scorecardJsonPath) ? scorecardJsonPath : "",
    runId: raw?.run_id ?? path.basename(resolvedRunDir),
    overallStatus: raw?.overall_status ?? "",
    goNoGo: raw?.go_no_go ?? "",
    trustScore: selectOverallTrustScore(raw),
    scoreSource: selectTrustScoreSource(raw),
    answerTrustScore: normalizeScore(raw?.answer_trust_score),
    governanceScore: normalizeScore(raw?.governance_score),
    empiricalScore: normalizeScore(raw?.empirical_score),
    evidenceCompleteness: normalizeScore(raw?.evidence_completeness, { scale: "raw" }),
  };
}

function resolveScorecardHtmlPath(artifactPath) {
  const resolvedArtifactPath = resolveFromBackend(artifactPath);
  const stat = fs.statSync(resolvedArtifactPath);
  const htmlPath = stat.isDirectory() ? path.join(resolvedArtifactPath, "scorecard.html") : resolvedArtifactPath;

  if (path.basename(htmlPath) !== "scorecard.html" || !fs.existsSync(htmlPath)) {
    throw new Error("Scorecard output is unavailable for this run.");
  }

  return htmlPath;
}

function selectOverallTrustScore(scorecard) {
  return (
    normalizeScore(scorecard?.answer_trust_score ?? scorecard?.answerTrustScore) ??
    normalizeScore(scorecard?.governance_score ?? scorecard?.governanceScore) ??
    normalizeScore(scorecard?.empirical_score ?? scorecard?.empiricalScore) ??
    normalizeScore(scorecard?.trust_score ?? scorecard?.trustScore)
  );
}

function selectTrustScoreSource(scorecard) {
  if (typeof (scorecard?.answer_trust_score ?? scorecard?.answerTrustScore) === "number") {
    return "Answer trust";
  }

  if (typeof (scorecard?.governance_score ?? scorecard?.governanceScore) === "number") {
    return "Governance score";
  }

  if (typeof (scorecard?.empirical_score ?? scorecard?.empiricalScore) === "number") {
    return "Empirical score";
  }

  if (typeof (scorecard?.trust_score ?? scorecard?.trustScore) === "number") {
    return "Trust score";
  }

  return "";
}

function normalizeScorecardPayload(scorecard) {
  if (!scorecard || typeof scorecard !== "object") {
    return null;
  }

  const trustScore = selectOverallTrustScore(scorecard);
  const answerTrustScore = normalizeScore(scorecard.answer_trust_score ?? scorecard.answerTrustScore);
  const governanceScore = normalizeScore(scorecard.governance_score ?? scorecard.governanceScore);
  const empiricalScore = normalizeScore(scorecard.empirical_score ?? scorecard.empiricalScore);

  return {
    ...scorecard,
    overallStatus: scorecard.overall_status ?? scorecard.overallStatus ?? "",
    goNoGo: scorecard.go_no_go ?? scorecard.goNoGo ?? "",
    trustScore,
    scoreSource: selectTrustScoreSource(scorecard),
    answerTrustScore,
    governanceScore,
    empiricalScore,
    evidenceCompleteness: normalizeScore(scorecard.evidence_completeness ?? scorecard.evidenceCompleteness, {
      scale: "raw",
    }),
  };
}

function normalizeScore(value, options = {}) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return null;
  }

  if (options.scale === "raw") {
    return Math.round(value * 10) / 10;
  }

  if (value <= 1) {
    return Math.round(value * 100);
  }

  return Math.round(value);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function resolveFromBackend(targetPath) {
  if (!targetPath) {
    return "";
  }

  return path.isAbsolute(targetPath) ? targetPath : path.resolve(__dirname, targetPath);
}

function parseCliArgs(rawValue = "") {
  const matches = rawValue.match(/(?:[^\s"]+|"[^"]*")+/g) ?? [];
  return matches.map((part) => part.replace(/^"|"$/g, ""));
}

function runCommand(command, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });

    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });

    child.on("error", reject);
    child.on("close", (exitCode) => {
      resolve({
        exitCode: exitCode ?? 1,
        stdout,
        stderr,
      });
    });
  });
}

function extractArtifactPath(stdout) {
  const match = stdout.match(/Artifacts:\s*(.+)$/m);
  return match?.[1]?.trim() ?? "";
}
