import cors from "cors";
import dotenv from "dotenv";
import express from "express";
import OpenAI from "openai";
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
    sessionMode: isGovernanceHookEnabled() ? "governance-enabled" : "local-chat",
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

function isGovernanceHookEnabled() {
  return String(process.env.KENTRO_ENABLE_GOVERNANCE_HOOK ?? "").toLowerCase() === "true";
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
    normalizeScore(scorecard?.answer_trust_score) ??
    normalizeScore(scorecard?.governance_score) ??
    normalizeScore(scorecard?.empirical_score)
  );
}

function selectTrustScoreSource(scorecard) {
  if (typeof scorecard?.answer_trust_score === "number") {
    return "Answer trust";
  }

  if (typeof scorecard?.governance_score === "number") {
    return "Governance score";
  }

  if (typeof scorecard?.empirical_score === "number") {
    return "Empirical score";
  }

  return "";
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
