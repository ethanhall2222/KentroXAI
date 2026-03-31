import { startTransition, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "kentro-chat-sessions";
const TOAST_DURATION_MS = 2800;

const onboardingPrompts = [
  {
    title: "Policy summary",
    prompt: "Summarize the latest policy update for an operations lead.",
  },
  {
    title: "Release checkpoint",
    prompt: "List the controls we should validate before release.",
  },
  {
    title: "Artifact preview",
    prompt: "What governance artifacts would this answer produce?",
  },
];

export default function App() {
  const initialSessionsRef = useRef(null);
  if (!initialSessionsRef.current) {
    initialSessionsRef.current = loadSessions();
  }

  const [sessions, setSessions] = useState(initialSessionsRef.current);
  const [currentSessionId, setCurrentSessionId] = useState(initialSessionsRef.current[0]?.id ?? "");
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [editingSessionId, setEditingSessionId] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [downloadSessionId, setDownloadSessionId] = useState("");
  const [toasts, setToasts] = useState([]);
  const scrollAnchorRef = useRef(null);

  const currentSession = sessions.find((session) => session.id === currentSessionId) ?? sessions[0];
  const downloadSession = sessions.find((session) => session.id === downloadSessionId) ?? null;
  const activeSessions = sessions.filter((session) => !session.archived);
  const archivedSessions = sessions.filter((session) => session.archived);
  const filteredActiveSessions = activeSessions.filter((session) => matchesSearch(session, searchQuery));
  const filteredArchivedSessions = archivedSessions.filter((session) => matchesSearch(session, searchQuery));
  const isEmptyState = currentSession ? !sessionHasUserMessages(currentSession) && !currentSession.archived : false;

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
          governanceState: payload.governanceHookEnabled ? "Hook armed" : "Hook idle",
          sessionPosture:
            payload.sessionMode === "governance-enabled" ? "Governance-ready mode" : "Local chat mode",
          statusText: payload.governanceHookEnabled
            ? "Backend ready. Governance handoff is armed for this session."
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

  if (!currentSession) {
    return null;
  }

  async function handleSubmit(event) {
    event.preventDefault();

    const nextMessage = draft.trim();
    if (!nextMessage || pending || currentSession.archived) {
      return;
    }

    const userMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: nextMessage,
      meta: {
        label: "You",
        timestamp: timeLabel(),
      },
    };

    startTransition(() => {
      updateCurrentSession((session) => ({
        ...session,
        messages: [...session.messages, userMessage],
        title: sessionHasUserMessages(session) ? session.title : titleFromPrompt(nextMessage),
        statusText: "Sending prompt to /api/chat...",
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
          history: [...currentSession.messages, userMessage].map(({ role, content }) => ({ role, content })),
        }),
      });

      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }

      const payload = await response.json();
      const assistantMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: payload.reply ?? "No reply returned from the server.",
        meta: buildGovernanceMeta(payload.governance),
      };

      startTransition(() => {
        updateCurrentSession((session) => ({
          ...session,
          messages: [...session.messages, assistantMessage],
          statusText: statusFromGovernance(payload.governance),
          modelName: payload.model ?? "local-scaffold",
          lastModelUsed: payload.model ?? "local-scaffold",
          governanceState: governanceLabel(payload.governance),
          sessionPosture: sessionPostureLabel(payload.governance),
          lastArtifactPath: payload.governance?.artifactPath ?? "",
          lastArtifactRunId: payload.governance?.artifactRunId ?? "",
          updatedAt: Date.now(),
        }));
      });

      if (payload.governance?.success) {
        pushToast(`Artifacts generated${payload.governance?.artifactRunId ? ` · ${payload.governance.artifactRunId}` : ""}`);
      }
    } catch (error) {
      startTransition(() => {
        updateCurrentSession((session) => ({
          ...session,
          messages: [
            ...session.messages,
            {
              id: crypto.randomUUID(),
              role: "assistant",
              content:
                "The scaffold backend did not answer cleanly. Check the Express server and try again.",
              meta: {
                label: "Error",
                timestamp: timeLabel(),
              },
            },
          ],
          statusText: error instanceof Error ? error.message : "Unexpected error",
          governanceState: "Backend issue",
          sessionPosture: "Backend issue",
          updatedAt: Date.now(),
        }));
      });
      pushToast("Backend issue");
    } finally {
      startTransition(() => {
        setPending(false);
      });
    }
  }

  function handleNewChat() {
    const nextSession = createSession({
      modelName: currentSession.modelName,
      lastModelUsed: currentSession.lastModelUsed || currentSession.modelName,
      governanceState: currentSession.governanceState,
      sessionPosture: currentSession.sessionPosture === "Backend issue" ? "Local chat mode" : currentSession.sessionPosture,
      statusText:
        currentSession.governanceState === "Hook armed"
          ? "Backend ready. Governance handoff is armed for this session."
          : "Backend ready for local chat.",
    });

    startTransition(() => {
      setSessions((current) => [nextSession, ...current]);
      setCurrentSessionId(nextSession.id);
      setPendingDeleteId("");
      setEditingSessionId("");
      setDownloadSessionId("");
      setSearchQuery("");
      setDraft("");
    });
    pushToast("New chat created");
  }

  function confirmDeleteSession(sessionId) {
    setPendingDeleteId(sessionId);
  }

  function cancelDeleteSession() {
    setPendingDeleteId("");
  }

  function handleDeleteSession(sessionId) {
    startTransition(() => {
      setSessions((current) => {
        const remaining = current.filter((session) => session.id !== sessionId);
        if (remaining.length === 0) {
          const replacement = createSession({
            modelName: currentSession.modelName,
            lastModelUsed: currentSession.lastModelUsed,
            governanceState: currentSession.governanceState,
            sessionPosture:
              currentSession.sessionPosture === "Backend issue"
                ? "Local chat mode"
                : currentSession.sessionPosture,
            statusText:
              currentSession.governanceState === "Hook armed"
                ? "Backend ready. Governance handoff is armed for this session."
                : "Backend ready for local chat.",
          });
          setCurrentSessionId(replacement.id);
          return [replacement];
        }

        if (sessionId === currentSessionId) {
          setCurrentSessionId((remaining.find((session) => !session.archived) ?? remaining[0]).id);
        }

        return remaining;
      });
      setPendingDeleteId("");
      setEditingSessionId("");
      setDownloadSessionId("");
    });
    pushToast("Chat deleted");
  }

  function handleArchiveSession(sessionId) {
    startTransition(() => {
      const fallback = activeSessions.find((session) => session.id !== sessionId);
      const replacement = !fallback && sessionId === currentSessionId
        ? createSession({
            modelName: currentSession.modelName,
            lastModelUsed: currentSession.lastModelUsed,
            governanceState: currentSession.governanceState,
            sessionPosture: "Local chat mode",
            statusText:
              currentSession.governanceState === "Hook armed"
                ? "Backend ready. Governance handoff is armed for this session."
                : "Backend ready for local chat.",
          })
        : null;

      setSessions((current) => {
        const archived = current.map((session) =>
          session.id === sessionId
            ? { ...session, archived: true, updatedAt: Date.now() }
            : session,
        );
        return replacement ? [replacement, ...archived] : archived;
      });

      if (sessionId === currentSessionId) {
        setCurrentSessionId(fallback ? fallback.id : replacement.id);
      }

      setPendingDeleteId("");
      setEditingSessionId("");
      setDownloadSessionId("");
    });
    pushToast("Chat archived");
  }

  function handleRestoreSession(sessionId) {
    startTransition(() => {
      setSessions((current) =>
        current.map((session) =>
          session.id === sessionId
            ? { ...session, archived: false, updatedAt: Date.now() }
            : session,
        ),
      );
      setCurrentSessionId(sessionId);
      setPendingDeleteId("");
      setEditingSessionId("");
      setDownloadSessionId("");
    });
    pushToast("Chat restored");
  }

  function startRenameSession(session) {
    setEditingSessionId(session.id);
    setTitleDraft(session.title);
  }

  function cancelRenameSession() {
    setEditingSessionId("");
    setTitleDraft("");
  }

  function saveRenameSession(sessionId) {
    const nextTitle = titleDraft.trim();
    if (!nextTitle) {
      cancelRenameSession();
      return;
    }

    startTransition(() => {
      setSessions((current) =>
        current.map((session) =>
          session.id === sessionId
            ? { ...session, title: nextTitle, updatedAt: Date.now() }
            : session,
        ),
      );
      setEditingSessionId("");
      setTitleDraft("");
    });
    pushToast("Title updated");
  }

  function updateCurrentSession(updater) {
    setSessions((current) =>
      current.map((session) => (session.id === currentSessionId ? updater(session) : session)),
    );
  }

  function pushToast(message) {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, { id, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, TOAST_DURATION_MS);
  }

  function exportSession(session, format) {
    const content =
      format === "json"
        ? JSON.stringify(session, null, 2)
        : sessionToMarkdown(session);
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
    setDownloadSessionId("");
    pushToast(`Exported ${extension.toUpperCase()}`);
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand-block">
          <span className="eyebrow">Kentro</span>
          <h1>Chat Workspace</h1>
          <p>Operational chat beside the governance engine, with status and artifact handoff kept in view.</p>
        </div>

        <button type="button" className="new-chat-button" onClick={handleNewChat}>
          New chat
        </button>

        <label className="search-box">
          <span className="search-label">Search chats</span>
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search titles, messages, or metadata..."
          />
        </label>

        <div className="sidebar-rail">
          <div className="rail-stat">
            <span className="rail-label">Current model</span>
            <strong>{currentSession.modelName}</strong>
          </div>
          <div className="rail-stat">
            <span className="rail-label">Governance</span>
            <strong>{currentSession.governanceState}</strong>
          </div>
          <div className="rail-stat">
            <span className="rail-label">Messages</span>
            <strong>{currentSession.messages.length}</strong>
          </div>
        </div>

        <section className="sidebar-panel">
          <h2>Saved chats</h2>
          <div className="history-list">
            {filteredActiveSessions.length === 0 ? (
              <p className="history-empty">No active chats match this search.</p>
            ) : (
              filteredActiveSessions.map((session) => (
                <div
                  key={session.id}
                  className={`history-item${session.id === currentSession.id ? " history-item-active" : ""}`}
                >
                  {editingSessionId === session.id ? (
                    <div className="history-main history-main-editing">
                      <input
                        className="history-title-input"
                        value={titleDraft}
                        onChange={(event) => setTitleDraft(event.target.value)}
                        placeholder="Rename chat"
                      />
                      <div className="history-meta-row">
                        <span>{session.sessionPosture}</span>
                        <time>{formatSessionTime(session.updatedAt)}</time>
                      </div>
                      <div className="history-badges">
                        <span className="history-badge">{session.lastModelUsed || session.modelName}</span>
                        <span className="history-badge">{session.governanceState}</span>
                        {session.lastArtifactRunId ? (
                          <span className="history-badge">Run {session.lastArtifactRunId}</span>
                        ) : null}
                      </div>
                    </div>
                  ) : (
                    <button type="button" className="history-main" onClick={() => setCurrentSessionId(session.id)}>
                      <strong>{session.title}</strong>
                      <div className="history-meta-row">
                        <span>{session.sessionPosture}</span>
                        <time>{formatSessionTime(session.updatedAt)}</time>
                      </div>
                      <div className="history-badges">
                        <span className="history-badge">{session.lastModelUsed || session.modelName}</span>
                        <span className="history-badge">{session.governanceState}</span>
                        {session.lastArtifactRunId ? (
                          <span className="history-badge">Run {session.lastArtifactRunId}</span>
                        ) : session.lastArtifactPath ? (
                          <span className="history-badge">Artifacts ready</span>
                        ) : null}
                      </div>
                    </button>
                  )}

                  <div className="history-actions">
                    {editingSessionId === session.id ? (
                      <>
                        <button type="button" className="history-save" onClick={() => saveRenameSession(session.id)}>
                          Save
                        </button>
                        <button type="button" className="history-cancel" onClick={cancelRenameSession}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <>
                        <button type="button" className="history-rename" onClick={() => startRenameSession(session)}>
                          Edit
                        </button>
                        <button type="button" className="history-archive" onClick={() => handleArchiveSession(session.id)}>
                          Archive
                        </button>
                        {pendingDeleteId === session.id ? (
                          <>
                            <button type="button" className="history-confirm" onClick={() => handleDeleteSession(session.id)}>
                              Confirm
                            </button>
                            <button type="button" className="history-cancel" onClick={cancelDeleteSession}>
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button type="button" className="history-delete" onClick={() => confirmDeleteSession(session.id)}>
                            Delete
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
          <button type="button" className="download-current-button" onClick={() => setDownloadSessionId(currentSession.id)}>
            Download current chat
          </button>
        </section>

        {archivedSessions.length > 0 ? (
          <section className="sidebar-panel">
            <h2>Archived chats</h2>
            <div className="history-list">
              {filteredArchivedSessions.length === 0 ? (
                <p className="history-empty">No archived chats match this search.</p>
              ) : (
                filteredArchivedSessions.map((session) => (
                  <div key={session.id} className="history-item history-item-archived">
                    <button type="button" className="history-main" onClick={() => setCurrentSessionId(session.id)}>
                      <strong>{session.title}</strong>
                      <div className="history-meta-row">
                        <span>{session.sessionPosture}</span>
                        <time>{formatSessionTime(session.updatedAt)}</time>
                      </div>
                      <div className="history-badges">
                        <span className="history-badge">{session.lastModelUsed || session.modelName}</span>
                        <span className="history-badge">{session.governanceState}</span>
                        {session.lastArtifactRunId ? (
                          <span className="history-badge">Run {session.lastArtifactRunId}</span>
                        ) : null}
                      </div>
                    </button>
                    <div className="history-actions">
                      <button type="button" className="history-restore" onClick={() => handleRestoreSession(session.id)}>
                        Restore
                      </button>
                      {pendingDeleteId === session.id ? (
                        <>
                          <button type="button" className="history-confirm" onClick={() => handleDeleteSession(session.id)}>
                            Confirm
                          </button>
                          <button type="button" className="history-cancel" onClick={cancelDeleteSession}>
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button type="button" className="history-delete" onClick={() => confirmDeleteSession(session.id)}>
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        ) : null}

      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div className="workspace-title">
            <span className="eyebrow">Companion App</span>
            <h2>{currentSession.title}</h2>
            <p>{currentSession.statusText}</p>
          </div>
          <div className="workspace-status">
            <div className="status-pill">{currentSession.archived ? "Archived" : pending ? "In flight" : "Ready"}</div>
            <div className="status-note">Model: {currentSession.modelName}</div>
          </div>
        </header>

        <section className="workspace-summary">
          <div>
            <span className="summary-label">Session posture</span>
            <strong>{currentSession.sessionPosture}</strong>
            <p>Replies can stay local or hand off into Kentro artifacts.</p>
          </div>
          <div>
            <span className="summary-label">Runtime</span>
            <strong>{pending ? "Request in progress" : "Express API available"}</strong>
            <p>The thread stays central while metadata stays nearby.</p>
          </div>
        </section>

        <section className="thread-intro">
          <div className="thread-intro-left">
            <span className="summary-label">Thread</span>
            <strong>Operator conversation</strong>
          </div>
          <div className="thread-tools">
            <p>
              {currentSession.archived
                ? "This chat is archived. Restore it from the sidebar before sending new messages."
                : "Use the thread for concise governance questions, release checks, and policy summaries."}
            </p>
          </div>
        </section>

        <section className="conversation">
          {currentSession.messages.map((message, index) => (
            <div key={message.id} className="message-stack">
              <article className={`message message-${message.role}`}>
                <div className="message-label">{message.meta?.label ?? message.role}</div>
                <p>{message.content}</p>
                <div className="message-meta">{message.meta?.timestamp ?? timeLabel()}</div>
              </article>
              {isEmptyState && index === 0 ? (
                <div className="onboarding-panel">
                  <span className="summary-label">Start here</span>
                  <h3>Choose a strong first prompt</h3>
                  <div className="onboarding-actions">
                    {onboardingPrompts.map((item) => (
                      <button key={item.title} type="button" className="onboarding-button" onClick={() => setDraft(item.prompt)}>
                        <strong>{item.title}</strong>
                        <span>{item.prompt}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ))}

          {pending ? (
            <article className="message message-assistant pending">
              <div className="message-label">Assistant</div>
              <p>Thinking through the local scaffold and governance handoff...</p>
              <div className="message-meta">Waiting for backend</div>
            </article>
          ) : null}
          <div ref={scrollAnchorRef} />
        </section>

        <form className="composer" onSubmit={handleSubmit}>
          <label className="composer-label" htmlFor="chat-input">
            Message
          </label>
          <textarea
            id="chat-input"
            rows="1"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            disabled={currentSession.archived}
            placeholder={
              currentSession.archived
                ? "This archived chat is read-only until restored..."
                : "Ask Kentro Chat for an answer, a summary, or a governance-ready draft..."
            }
          />
          <div className="composer-footer">
            <p>
              {currentSession.archived
                ? "Archived chats are view-only. Restore the chat to continue the conversation."
                : "Replies come from the local Express scaffold until a live model is connected."}
            </p>
            <button type="submit" disabled={currentSession.archived || pending || !draft.trim()}>
              {pending ? "Sending..." : "Send message"}
            </button>
          </div>
        </form>
      </main>

      <div className="toast-stack">
        {toasts.map((toast) => (
          <div key={toast.id} className="toast">
            {toast.message}
          </div>
        ))}
      </div>

      {downloadSession ? (
        <div className="modal-backdrop" onClick={() => setDownloadSessionId("")}>
          <div className="download-modal" onClick={(event) => event.stopPropagation()}>
            <span className="summary-label">Download chat</span>
            <h3>{downloadSession.title}</h3>
            <p>Choose a format for this conversation export.</p>
            <div className="download-actions">
              <button type="button" className="export-button" onClick={() => exportSession(downloadSession, "md")}>
                Markdown
              </button>
              <button type="button" className="export-button" onClick={() => exportSession(downloadSession, "json")}>
                JSON
              </button>
              <button type="button" className="modal-cancel" onClick={() => setDownloadSessionId("")}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function loadSessions() {
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
      lastModelUsed: session.lastModelUsed ?? session.modelName ?? "local-scaffold",
    }));
  } catch {
    return [createSession()];
  }
}

function createSession(overrides = {}) {
  return {
    id: crypto.randomUUID(),
    title: "New chat",
    messages: createStarterMessages(),
    modelName: "local-scaffold",
    lastModelUsed: "local-scaffold",
    governanceState: "Hook idle",
    sessionPosture: "Local chat mode",
    statusText: "Checking local backend status...",
    archived: false,
    lastArtifactPath: "",
    lastArtifactRunId: "",
    updatedAt: Date.now(),
    ...overrides,
  };
}

function createStarterMessages() {
  return [
    {
      id: crypto.randomUUID(),
      role: "assistant",
      content:
        "Kentro Chat is ready. Ask for a policy summary, a governance checkpoint, or a release-readiness explanation.",
      meta: {
        label: "Scaffold",
        timestamp: timeLabel(),
      },
    },
  ];
}

function sessionHasUserMessages(session) {
  return session.messages.some((message) => message.role === "user");
}

function titleFromPrompt(prompt) {
  const normalized = prompt.replace(/\s+/g, " ").trim();
  return normalized.length > 36 ? `${normalized.slice(0, 36)}...` : normalized;
}

function buildGovernanceMeta(governance) {
  if (!governance?.enabled) {
    return {
      label: "Assistant",
      timestamp: `${timeLabel()} · Governance hook off`,
    };
  }

  if (governance.success) {
    return {
      label: "Assistant",
      timestamp: `${timeLabel()} · Artifacts generated`,
    };
  }

  return {
    label: "Assistant",
    timestamp: `${timeLabel()} · Hook attempted`,
  };
}

function statusFromGovernance(governance) {
  if (!governance?.enabled) {
    return "Reply returned locally. Governance hook is disabled.";
  }

  if (governance.success) {
    return "Reply returned and the Kentro CLI hook completed successfully.";
  }

  return "Reply returned, but the Kentro CLI hook needs attention.";
}

function governanceLabel(governance) {
  if (!governance?.enabled) {
    return "Hook idle";
  }

  if (governance.success) {
    return "Artifacts generated";
  }

  if (governance.attempted) {
    return "Hook attempted";
  }

  return "Hook idle";
}

function sessionPostureLabel(governance) {
  if (!governance?.enabled) {
    return "Local chat mode";
  }

  if (governance.success) {
    return "Governance run complete";
  }

  if (governance.attempted) {
    return "Governance handoff attempted";
  }

  return "Local chat mode";
}

function formatSessionTime(timestamp) {
  return new Date(timestamp).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function matchesSearch(session, searchQuery) {
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
    session.lastArtifactRunId,
    session.lastArtifactPath,
    ...session.messages.map((message) => message.content),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  return haystack.includes(query);
}

function sessionToMarkdown(session) {
  const header = [
    `# ${session.title}`,
    "",
    `- Session posture: ${session.sessionPosture}`,
    `- Governance: ${session.governanceState}`,
    `- Model: ${session.lastModelUsed || session.modelName}`,
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

function slugify(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "kentro-chat";
}

function timeLabel() {
  return new Date().toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}
