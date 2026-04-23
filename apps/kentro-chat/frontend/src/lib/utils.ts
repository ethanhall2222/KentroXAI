import type { ChatSession, GovernanceTone } from "../types";

export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function formatSessionTime(timestamp: number) {
  return new Date(timestamp).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function timeLabel() {
  return new Date().toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function titleFromPrompt(prompt: string) {
  const normalized = prompt.replace(/\s+/g, " ").trim();
  return normalized.length > 36 ? `${normalized.slice(0, 36)}...` : normalized;
}

export function slugify(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "kentro-chat";
}

export function normalizeTrustScoreValue(score: number | null | undefined) {
  if (typeof score !== "number" || Number.isNaN(score)) {
    return null;
  }

  if (score <= 1) {
    return score * 100;
  }

  return score;
}

export function formatTrustScoreValue(score: number | null | undefined) {
  const normalized = normalizeTrustScoreValue(score);
  if (normalized === null) {
    return "N/A";
  }

  return `${Math.round(normalized)}%`;
}

export function trustTone(score: number | null | undefined, overallStatus: string) {
  if (overallStatus === "fail") {
    return "danger";
  }

  if (overallStatus === "needs_review") {
    return "warning";
  }

  const normalized = normalizeTrustScoreValue(score);
  if (normalized !== null) {
    if (normalized >= 80) {
      return "success";
    }

    if (normalized >= 60) {
      return "warning";
    }

    return "danger";
  }

  return "neutral";
}

export function statusToneForGovernance(governanceState: string): GovernanceTone {
  if (governanceState === "Artifacts generated") {
    return "success";
  }

  if (
    governanceState === "Hook attempted" ||
    governanceState === "Hook armed" ||
    governanceState === "Job attempted" ||
    governanceState === "Job backend armed"
  ) {
    return "warning";
  }

  if (governanceState === "Backend issue") {
    return "danger";
  }

  return "neutral";
}

export function sessionHasUserMessages(session: ChatSession) {
  return session.messages.some((message) => message.role === "user");
}

export function matchesSearch(session: ChatSession, searchQuery: string) {
  const query = searchQuery.trim().toLowerCase();
  if (!query) {
    return true;
  }

  const haystack = [
    session.title,
    session.sessionPosture,
    session.governanceState,
    session.modelName,
    session.lastModelUsed,
    session.lastTrustScore,
    session.lastTrustScoreSource,
    session.lastOverallStatus,
    session.lastGoNoGo,
    session.lastArtifactRunId,
    session.lastArtifactPath,
    ...session.messages.map((message) => message.content),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return haystack.includes(query);
}

export function sessionToMarkdown(session: ChatSession) {
  const header = [
    `# ${session.title}`,
    "",
    `- Session posture: ${session.sessionPosture}`,
    `- Governance: ${session.governanceState}`,
    `- Model: ${session.lastModelUsed || session.modelName}`,
    session.lastTrustScore !== null && session.lastTrustScore !== undefined
      ? `- Overall trust score: ${formatTrustScoreValue(session.lastTrustScore)}`
      : "",
    session.lastOverallStatus ? `- Overall status: ${session.lastOverallStatus}` : "",
    session.lastGoNoGo ? `- Go / no-go: ${session.lastGoNoGo}` : "",
    session.lastArtifactRunId ? `- Artifact run: ${session.lastArtifactRunId}` : "",
    session.lastArtifactPath ? `- Artifact path: ${session.lastArtifactPath}` : "",
    "",
  ]
    .filter(Boolean)
    .join("\n");

  const body = session.messages
    .map((message) => `## ${message.role}\n\n${message.content}\n`)
    .join("\n");

  return `${header}${body}`.trim();
}
