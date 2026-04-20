import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatContainer } from "./components/ChatContainer";
import { InputBar } from "./components/InputBar";
import { Button } from "./components/Button";
import { Drawer } from "./components/Drawer";
import { Modal } from "./components/Modal";
import { CollapsibleSection } from "./components/CollapsibleSection";
import { Icon } from "./components/Icon";
import type { ChatMessage, ChatSession, GovernanceTone } from "./types";
import {
  cn,
  formatTrustScoreValue,
  matchesSearch,
  sessionHasUserMessages,
  sessionToMarkdown,
  slugify,
  statusToneForGovernance,
  timeLabel,
  titleFromPrompt,
  trustTone,
} from "./lib/utils";

const STORAGE_KEY = "kentro-chat-sessions";
const TOAST_DURATION_MS = 2800;

const onboardingPrompts = [
  {
    title: "Policy brief",
    prompt: "Summarize the latest policy update for an operations lead in plain language.",
  },
  {
    title: "Release check",
    prompt: "List the controls we should validate before release and call out blockers.",
  },
  {
    title: "Artifact plan",
    prompt: "What governance artifacts would this answer produce and what would each one show?",
  },
];

type GovernancePayload = {
  enabled?: boolean;
  success?: boolean;
  attempted?: boolean;
  mode?: string;
  artifactPath?: string;
  artifactRunId?: string;
  scorecardHtml?: string;
  scorecardJsonPath?: string;
  scorecard?: {
    trustScore?: number | null;
    htmlUrl?: string;
    htmlPath?: string;
    jsonPath?: string;
    overallStatus?: string;
    goNoGo?: string;
    evidenceCompleteness?: number | null;
    scoreSource?: string;
  };
  answerTrustScore?: number | null;
  overallStatus?: string;
  goNoGo?: string;
};

type ErrorPayload = {
  error?: string;
  details?: string;
};

export default function App() {
  const initialSessionsRef = useRef<ChatSession[] | null>(null);
  if (!initialSessionsRef.current) {
    initialSessionsRef.current = loadSessions();
  }

  const [sessions, setSessions] = useState<ChatSession[]>(initialSessionsRef.current);
  const [currentSessionId, setCurrentSessionId] = useState(initialSessionsRef.current[0]?.id ?? "");
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [toasts, setToasts] = useState<Array<{ id: string; message: string }>>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [scorecardOpen, setScorecardOpen] = useState(false);
  const scrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const deferredSearchQuery = useDeferredValue(searchQuery);
  const currentSession = sessions.find((session) => session.id === currentSessionId) ?? sessions[0];
  const activeSessions = sessions.filter((session) => !session.archived);
  const archivedSessions = sessions.filter((session) => session.archived);
  const filteredActiveSessions = activeSessions.filter((session) => matchesSearch(session, deferredSearchQuery));
  const filteredArchivedSessions = archivedSessions.filter((session) => matchesSearch(session, deferredSearchQuery));

  useEffect(() => {
    if (!currentSession && sessions.length > 0) {
      setCurrentSessionId((activeSessions[0] ?? sessions[0]).id);
    }
  }, [activeSessions, currentSession, sessions]);

  useEffect(() => {
    scrollAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [currentSession?.messages, pending]);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      try {
        const response = await fetch("/api/health");
        if (!response.ok) {
          throw new Error(`Health check failed with status ${response.status}`);
        }

        const payload = await response.json();
        if (cancelled) {
          return;
        }

        updateCurrentSession((session) => ({
          ...session,
          modelName: payload.model ?? "local-scaffold",
          lastModelUsed: payload.model ?? "local-scaffold",
          governanceState: payload.jobBackendEnabled
            ? "Job backend armed"
            : payload.governanceHookEnabled
              ? "Hook armed"
              : "Governance idle",
          sessionPosture:
            payload.sessionMode === "databricks-job"
              ? "Databricks job mode"
              : payload.sessionMode === "governance-enabled"
                ? "Governance-ready mode"
                : "Local chat mode",
          statusText: payload.jobBackendEnabled
            ? "Databricks job execution is armed for governed responses."
            : payload.liveModelReady
              ? payload.governanceHookEnabled
                ? "Live model connected and governance handoff is armed."
                : "Live model connected for operator chat."
              : payload.governanceHookEnabled
                ? "Governance handoff is armed for this session."
                : "Backend ready for local chat.",
        }));
      } catch (error) {
        if (cancelled) {
          return;
        }

        updateCurrentSession((session) => ({
          ...session,
          governanceState: "Backend issue",
          sessionPosture: "Backend issue",
          statusText: error instanceof Error ? error.message : "Unable to reach backend",
        }));
      }
    }

    loadHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  const trustSummary = useMemo(() => trustSummaryForSession(currentSession), [currentSession]);
  const statusTone: GovernanceTone = currentSession
    ? currentSession.archived
      ? "neutral"
      : pending
        ? "warning"
        : currentSession.governanceState === "Backend issue"
          ? "danger"
          : "success"
    : "neutral";

  const isEmptyState = currentSession ? !sessionHasUserMessages(currentSession) && !currentSession.archived : false;

  const detailRows = [
    { label: "Model", value: currentSession?.modelName ?? "Unknown" },
    { label: "Trust", value: trustSummary.displayValue },
    { label: "Governance", value: currentSession?.governanceState ?? "Unknown" },
    { label: "Messages", value: String(currentSession?.messages.length ?? 0) },
  ];

  if (!currentSession) {
    return null;
  }

  async function handleSend(nextMessage: string, options?: { includeUserMessage?: boolean }) {
    if (!nextMessage.trim() || pending || currentSession.archived) {
      return;
    }

    const includeUserMessage = options?.includeUserMessage ?? true;
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: nextMessage,
      meta: {
        label: "You",
        timestamp: timeLabel(),
      },
    };

    const historyBase = includeUserMessage
      ? [...currentSession.messages, userMessage]
      : currentSession.messages.filter((message) => message.meta?.kind !== "error");

    startTransition(() => {
      updateCurrentSession((session) => ({
        ...session,
        messages: includeUserMessage ? [...session.messages, userMessage] : session.messages,
        title: sessionHasUserMessages(session) ? session.title : titleFromPrompt(nextMessage),
        updatedAt: Date.now(),
      }));
      setDraft("");
      setPending(true);
    });

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: nextMessage,
          history: historyBase.map(({ role, content }) => ({ role, content })),
        }),
      });

      if (!response.ok) {
        const errorPayload = (await response.json().catch(() => null)) as ErrorPayload | null;
        const summary = errorPayload?.error?.trim() || `Request failed with status ${response.status}`;
        const details = errorPayload?.details?.trim() || "";
        throw new Error(details ? `${summary}\n\n${details}` : summary);
      }

      const payload = await response.json();
      const assistantMessage: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: payload.reply ?? "No reply returned from the server.",
        meta: buildGovernanceMeta(payload.governance),
      };

      startTransition(() => {
        const scorecard = payload.governance?.scorecard ?? null;
        const artifactPath = payload.governance?.artifactPath ?? "";
        const scorecardHtml = payload.governance?.scorecardHtml ?? "";
        const derivedScorecardUrl = scorecardHtml
          ? URL.createObjectURL(new Blob([scorecardHtml], { type: "text/html" }))
          : scorecard?.htmlUrl ?? "";
        const trustValue = scorecard?.trustScore ?? payload.governance?.answerTrustScore ?? null;

        updateCurrentSession((session) => ({
          ...session,
          messages: [...session.messages.filter((message) => message.meta?.kind !== "error"), assistantMessage],
          modelName: payload.model ?? "local-scaffold",
          lastModelUsed: payload.model ?? "local-scaffold",
          governanceState: governanceLabel(payload.governance),
          sessionPosture: sessionPostureLabel(payload.governance),
          statusText: statusFromGovernance(payload.governance, payload.model),
          lastArtifactPath: artifactPath,
          lastArtifactRunId: payload.governance?.artifactRunId ?? "",
          lastScorecardUrl: derivedScorecardUrl,
          lastScorecardHtmlPath: scorecard?.htmlPath ?? "",
          lastScorecardJsonPath: payload.governance?.scorecardJsonPath ?? scorecard?.jsonPath ?? "",
          lastTrustScore: trustValue,
          lastTrustScoreSource:
            scorecard?.scoreSource ??
            (payload.governance?.answerTrustScore !== null && payload.governance?.answerTrustScore !== undefined
              ? "Answer trust"
              : ""),
          lastOverallStatus: scorecard?.overallStatus ?? payload.governance?.overallStatus ?? "",
          lastGoNoGo: scorecard?.goNoGo ?? payload.governance?.goNoGo ?? "",
          lastEvidenceCompleteness: scorecard?.evidenceCompleteness ?? null,
          updatedAt: Date.now(),
        }));
      });

      if (payload.governance?.success) {
        const trustValue =
          payload.governance?.scorecard?.trustScore ??
          payload.governance?.answerTrustScore ??
          null;
        pushToast(
          `Scorecard ready${payload.governance?.artifactRunId ? ` · ${payload.governance.artifactRunId}` : ""}${trustValue !== null && trustValue !== undefined ? ` · Trust ${formatTrustScoreValue(trustValue)}` : ""}`,
        );
      }
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unexpected error";
      startTransition(() => {
        updateCurrentSession((session) => ({
          ...session,
          messages: [
            ...session.messages.filter((message) => message.meta?.kind !== "error"),
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content: "The request could not be completed. Please try again.",
              meta: {
                label: "Kentro",
                timestamp: `${timeLabel()} · Delivery issue`,
                kind: "error",
                detail,
              },
              retryPrompt: nextMessage,
            },
          ],
          governanceState: "Backend issue",
          sessionPosture: "Backend issue",
          statusText: detail,
          updatedAt: Date.now(),
        }));
      });
      pushToast("Request failed");
    } finally {
      startTransition(() => {
        setPending(false);
      });
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void handleSend(draft);
  }

  function handleRetry(prompt: string) {
    void handleSend(prompt, { includeUserMessage: false });
  }

  function handleNewChat() {
    const nextSession = createSession({
      modelName: currentSession.modelName,
      lastModelUsed: currentSession.lastModelUsed || currentSession.modelName,
      governanceState: currentSession.governanceState,
      sessionPosture: currentSession.sessionPosture === "Backend issue" ? "Local chat mode" : currentSession.sessionPosture,
      statusText: currentSession.statusText,
    });

    startTransition(() => {
      setSessions((current) => [nextSession, ...current]);
      setCurrentSessionId(nextSession.id);
      setDraft("");
      setSearchQuery("");
    });
  }

  function handleArchiveSession(sessionId: string) {
    startTransition(() => {
      const fallback = activeSessions.find((session) => session.id !== sessionId);
      const replacement = !fallback && sessionId === currentSessionId ? createSession() : null;

      setSessions((current) => {
        const archived = current.map((session) =>
          session.id === sessionId ? { ...session, archived: true, updatedAt: Date.now() } : session,
        );
        return replacement ? [replacement, ...archived] : archived;
      });

      if (sessionId === currentSessionId) {
        setCurrentSessionId(fallback ? fallback.id : replacement!.id);
      }
    });
  }

  function handleRestoreSession(sessionId: string) {
    startTransition(() => {
      setSessions((current) =>
        current.map((session) =>
          session.id === sessionId ? { ...session, archived: false, updatedAt: Date.now() } : session,
        ),
      );
      setCurrentSessionId(sessionId);
    });
  }

  function handleDeleteSession(sessionId: string) {
    startTransition(() => {
      setSessions((current) => {
        const remaining = current.filter((session) => session.id !== sessionId);
        if (remaining.length === 0) {
          const replacement = createSession();
          setCurrentSessionId(replacement.id);
          return [replacement];
        }
        if (sessionId === currentSessionId) {
          setCurrentSessionId((remaining.find((session) => !session.archived) ?? remaining[0]).id);
        }
        return remaining;
      });
    });
  }

  function handleRenameSession(session: ChatSession) {
    const nextTitle = window.prompt("Rename chat", session.title)?.trim();
    if (!nextTitle) {
      return;
    }

    startTransition(() => {
      setSessions((current) =>
        current.map((item) => (item.id === session.id ? { ...item, title: nextTitle, updatedAt: Date.now() } : item)),
      );
    });
  }

  function updateCurrentSession(updater: (session: ChatSession) => ChatSession) {
    setSessions((current) =>
      current.map((session) => (session.id === currentSessionId ? updater(session) : session)),
    );
  }

  function pushToast(message: string) {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, { id, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, TOAST_DURATION_MS);
  }

  function exportSession(format: "json" | "md") {
    const session = currentSession;
    const content = format === "json" ? JSON.stringify(session, null, 2) : sessionToMarkdown(session);
    const extension = format === "json" ? "json" : "md";
    const type = format === "json" ? "application/json" : "text/markdown";
    const filename = `${slugify(session.title)}.${extension}`;
    const blob = new Blob([content], { type });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
    pushToast(`Exported ${extension.toUpperCase()}`);
  }

  return (
    <div className="min-h-screen p-4">
      <div className="mx-auto grid max-w-[1600px] gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <Sidebar
          sessions={filteredActiveSessions}
          archivedSessions={filteredArchivedSessions}
          activeSessionId={currentSession.id}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          onSelectSession={setCurrentSessionId}
          onNewChat={handleNewChat}
          onArchive={handleArchiveSession}
          onRestore={handleRestoreSession}
          onDelete={handleDeleteSession}
          onRename={handleRenameSession}
        />

        <main className="relative flex h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-[32px] border border-slate-200 bg-slate-50/70 shadow-sm backdrop-blur">
          <header className="border-b border-slate-200/80 bg-slate-50/90 px-4 py-4 backdrop-blur sm:px-6">
            <div className="mx-auto flex w-full max-w-4xl items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Kentro Chat</p>
                <h2 className="truncate pt-1 text-lg font-semibold text-slate-900">{currentSession.title}</h2>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="subtle" className="rounded-full px-4" onClick={() => setScorecardOpen(true)}>
                  Generate Scorecard
                </Button>
                <Button variant="ghost" className="rounded-full px-4" onClick={() => setDrawerOpen(true)}>
                  <Icon name="panel" className="h-4 w-4" />
                  View insights
                </Button>
              </div>
            </div>
          </header>

          <div className="flex-1 overflow-y-auto">
            <ChatContainer
              empty={isEmptyState}
              messages={currentSession.messages}
              pending={pending}
              prompts={onboardingPrompts}
              onPromptSelect={setDraft}
              onRetry={handleRetry}
              scrollAnchorRef={scrollAnchorRef}
            />
          </div>

          <InputBar
            draft={draft}
            disabled={currentSession.archived}
            pending={pending}
            onChange={setDraft}
            onSubmit={handleSubmit}
            onOpenScorecard={() => setScorecardOpen(true)}
          />
        </main>
      </div>

      <Drawer open={drawerOpen} title="Session insights" onClose={() => setDrawerOpen(false)}>
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {detailRows.map((item) => (
              <div key={item.label} className="rounded-2xl border border-slate-200 bg-white p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</p>
                <p className="mt-2 text-sm font-semibold text-slate-900">{item.value}</p>
              </div>
            ))}
          </div>

          <CollapsibleSection title="Governance summary" defaultOpen>
            <div className="space-y-2">
              <DetailRow label="Status" value={currentSession.governanceState} />
              <DetailRow label="Posture" value={currentSession.sessionPosture} />
              <DetailRow label="Overall status" value={currentSession.lastOverallStatus || "Not available"} />
              <DetailRow label="Go / no-go" value={currentSession.lastGoNoGo || "Not available"} />
              <DetailRow
                label="Evidence completeness"
                value={currentSession.lastEvidenceCompleteness !== null ? `${Math.round(currentSession.lastEvidenceCompleteness)}%` : "Not available"}
              />
            </div>
          </CollapsibleSection>

          <CollapsibleSection title="Backend details">
            <div className="space-y-2">
              <DetailRow label="Current model" value={currentSession.modelName} />
              <DetailRow label="Last artifact run" value={currentSession.lastArtifactRunId || "Not available"} />
              <DetailRow label="Artifact path" value={currentSession.lastArtifactPath || "Not available"} />
              <DetailRow label="Scorecard JSON" value={currentSession.lastScorecardJsonPath || "Not available"} />
              <div className="rounded-2xl bg-slate-50 p-3 text-sm leading-6 text-slate-600">
                {currentSession.statusText}
              </div>
            </div>
          </CollapsibleSection>

          <CollapsibleSection title="Actions">
            <div className="flex flex-wrap gap-2">
              <Button variant="ghost" className="rounded-xl" onClick={() => exportSession("md")}>
                Export Markdown
              </Button>
              <Button variant="ghost" className="rounded-xl" onClick={() => exportSession("json")}>
                Export JSON
              </Button>
            </div>
          </CollapsibleSection>
        </div>
      </Drawer>

      <Modal open={scorecardOpen} title="Kentro scorecard" onClose={() => setScorecardOpen(false)}>
        {currentSession.lastScorecardUrl ? (
          <iframe
            title="Kentro scorecard"
            src={currentSession.lastScorecardUrl}
            className="h-full w-full border-0"
          />
        ) : (
          <div className="flex h-full items-center justify-center bg-slate-50 px-6">
            <div className="max-w-lg space-y-3 text-center">
              <p className="text-xs uppercase tracking-[0.2em] text-slate-500">No scorecard yet</p>
              <h3 className="text-2xl font-semibold tracking-tight text-slate-900">
                Send a message to generate the latest scorecard.
              </h3>
              <p className="text-sm leading-7 text-slate-600">
                Scorecards are created from the backend governance run. Once a reply completes, you can open the full scorecard here.
              </p>
            </div>
          </div>
        )}
      </Modal>

      <div className="pointer-events-none fixed bottom-4 right-4 z-50 grid gap-2">
        {toasts.map((toast) => (
          <div key={toast.id} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 shadow-lg">
            {toast.message}
          </div>
        ))}
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-2xl bg-slate-50 px-3 py-2">
      <span className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</span>
      <span className="break-words text-sm text-slate-700">{value}</span>
    </div>
  );
}

function loadSessions(): ChatSession[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [createSession()];
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return [createSession()];
    }

    return parsed.map((session) => ({
      ...createSession(),
      ...session,
      archived: Boolean(session.archived),
      lastArtifactPath: session.lastArtifactPath ?? "",
      lastArtifactRunId: session.lastArtifactRunId ?? "",
      lastScorecardUrl: "",
      lastScorecardHtmlPath: session.lastScorecardHtmlPath ?? "",
      lastScorecardJsonPath: session.lastScorecardJsonPath ?? "",
      lastTrustScore: session.lastTrustScore ?? null,
      lastTrustScoreSource: session.lastTrustScoreSource ?? "",
      lastOverallStatus: session.lastOverallStatus ?? "",
      lastGoNoGo: session.lastGoNoGo ?? "",
      lastEvidenceCompleteness: session.lastEvidenceCompleteness ?? null,
      lastModelUsed: session.lastModelUsed ?? session.modelName ?? "local-scaffold",
    }));
  } catch {
    return [createSession()];
  }
}

function createSession(overrides: Partial<ChatSession> = {}): ChatSession {
  return {
    id: crypto.randomUUID(),
    title: "New chat",
    messages: [],
    modelName: "local-scaffold",
    lastModelUsed: "local-scaffold",
    governanceState: "Governance idle",
    sessionPosture: "Local chat mode",
    statusText: "Backend ready for local chat.",
    archived: false,
    lastArtifactPath: "",
    lastArtifactRunId: "",
    lastScorecardUrl: "",
    lastScorecardHtmlPath: "",
    lastScorecardJsonPath: "",
    lastTrustScore: null,
    lastTrustScoreSource: "",
    lastOverallStatus: "",
    lastGoNoGo: "",
    lastEvidenceCompleteness: null,
    updatedAt: Date.now(),
    ...overrides,
  };
}

function buildGovernanceMeta(governance?: GovernancePayload): ChatMessage["meta"] {
  if (!governance?.enabled) {
    return {
      label: "Kentro",
      timestamp: `${timeLabel()} · Governance off`,
    };
  }

  const trustValue = governance.scorecard?.trustScore ?? governance.answerTrustScore ?? null;

  if (governance.success) {
    return {
      label: "Kentro",
      timestamp:
        trustValue !== null && trustValue !== undefined
          ? `${timeLabel()} · Trust ${formatTrustScoreValue(trustValue)}`
          : `${timeLabel()} · Scorecard ready`,
    };
  }

  return {
    label: "Kentro",
    timestamp: `${timeLabel()} · Governance attempted`,
  };
}

function statusFromGovernance(governance: GovernancePayload | undefined, modelName: string) {
  if (!governance?.enabled) {
    return modelName === "local-scaffold"
      ? "Reply returned locally. Governance is disabled."
      : "Reply returned from the live model. Governance is disabled.";
  }

  const trustValue = governance.scorecard?.trustScore ?? governance.answerTrustScore ?? null;

  if (governance.success) {
    return trustValue !== null && trustValue !== undefined
      ? `Reply returned and Kentro generated a scorecard with a trust score of ${formatTrustScoreValue(trustValue)}.`
      : governance.mode === "databricks-job"
        ? "Reply returned and the Databricks governance job completed successfully."
        : "Reply returned and the Kentro CLI hook completed successfully.";
  }

  return governance.mode === "databricks-job"
    ? "Reply returned, but the Databricks governance job needs attention."
    : "Reply returned, but the Kentro CLI hook needs attention.";
}

function governanceLabel(governance?: GovernancePayload) {
  if (!governance?.enabled) {
    return "Governance idle";
  }

  if (governance.success) {
    return "Artifacts generated";
  }

  if (governance.attempted) {
    return governance.mode === "databricks-job" ? "Job attempted" : "Hook attempted";
  }

  return "Governance idle";
}

function sessionPostureLabel(governance?: GovernancePayload) {
  if (!governance?.enabled) {
    return "Local chat mode";
  }

  if (governance.success) {
    return governance.mode === "databricks-job"
      ? "Databricks governance run complete"
      : "Governance run complete";
  }

  if (governance.attempted) {
    return governance.mode === "databricks-job"
      ? "Databricks governance handoff attempted"
      : "Governance handoff attempted";
  }

  return "Local chat mode";
}

function trustSummaryForSession(session: ChatSession) {
  if (session.lastTrustScore !== null && session.lastTrustScore !== undefined) {
    return {
      displayValue: formatTrustScoreValue(session.lastTrustScore),
      subLabel: session.lastTrustScoreSource || "Latest governance scorecard",
      statusLabel: session.lastGoNoGo ? session.lastGoNoGo.replace("-", " ") : session.lastOverallStatus || "Available",
      helperText: session.lastOverallStatus
        ? `Overall status: ${session.lastOverallStatus.replace("_", " ")}`
        : "Latest score from the most recent governance run",
      tone: trustTone(session.lastTrustScore, session.lastOverallStatus),
    };
  }

  return {
    displayValue: "Awaiting run",
    subLabel: "No scorecard yet",
    statusLabel: session.governanceState,
    helperText: "Use the scorecard button or send a message to generate one from the backend governance run.",
    tone: "neutral" as GovernanceTone,
  };
}
