import cors from "cors";
import dotenv from "dotenv";
import express from "express";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const app = express();

const PORT = Number.parseInt(process.env.PORT ?? "5050", 10);
const FRONTEND_ORIGIN = process.env.FRONTEND_ORIGIN ?? "http://localhost:5173";
const CHAT_MODEL = process.env.KENTRO_CHAT_MODEL ?? "local-scaffold";
const repoRoot = path.resolve(__dirname, "../../..");
const defaultConfigPath = path.resolve(__dirname, "../../../config.yaml");

app.use(cors({ origin: FRONTEND_ORIGIN }));
app.use(express.json({ limit: "1mb" }));

app.get("/api/health", (_req, res) => {
  res.json({
    ok: true,
    service: "kentro-chat-backend",
    repoRoot,
    model: CHAT_MODEL,
    governanceHookEnabled: isGovernanceHookEnabled(),
    sessionMode: isGovernanceHookEnabled() ? "governance-enabled" : "local-chat",
  });
});

app.post("/api/chat", async (req, res) => {
  const message = typeof req.body?.message === "string" ? req.body.message.trim() : "";
  const history = Array.isArray(req.body?.history) ? req.body.history : [];

  if (!message) {
    res.status(400).json({ error: "A non-empty `message` field is required." });
    return;
  }

  const reply = buildScaffoldReply(message, history);
  const governance = await maybeRunGovernanceHook({ message, reply });

  res.json({
    reply,
    model: CHAT_MODEL,
    governance,
  });
});

app.listen(PORT, () => {
  console.log(`Kentro chat backend listening on http://localhost:${PORT}`);
});

function buildScaffoldReply(message, history) {
  const normalized = message.replace(/\s+/g, " ").trim();
  const priorTurns = history.filter((entry) => entry && typeof entry.content === "string").length;

  const responseParts = [
    "This is the Kentro chat scaffold speaking through the local Express API.",
    `I received: \"${normalized}\"`,
    priorTurns > 0
      ? `I can also see ${priorTurns} earlier message${priorTurns === 1 ? "" : "s"} in the conversation context.`
      : "This looks like the first turn in the current conversation.",
    "Once a real model is connected, this endpoint can swap the stubbed reply for live output without changing the frontend contract.",
  ];

  return responseParts.join(" ");
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
    return {
      enabled: true,
      attempted: true,
      success: result.exitCode === 0,
      exitCode: result.exitCode,
      command: [cliBin, ...commandArgs].join(" "),
      artifactPath,
      artifactRunId: artifactPath ? path.basename(artifactPath) : "",
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
