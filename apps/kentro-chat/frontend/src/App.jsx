import { startTransition, useDeferredValue, useEffect, useRef, useState } from "react";

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

const sidebarGroups = [
  { label: "Workspace", items: [{ icon: "spark", label: "Kentro Chat", active: true }] },
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

  const deferredSearchQuery = useDeferredValue(searchQuery);
  const currentSession = sessions.find((session) => session.id === currentSessionId) ?? sessions[0];
  const downloadSession = sessions.find((session) => session.id === downloadSessionId) ?? null;
  const activeSessions = sessions.filter((session) => !session.archived);
  const archivedSessions = sessions.filter((session) => session.archived);
  const filteredActiveSessions = activeSessions.filter((session) => matchesSearch(session, deferredSearchQuery));
  const filteredArchivedSessions = archivedSessions.filter((session) => matchesSearch(session, deferredSearchQuery));
  const isEmptyState = currentSession ? !sessionHasUserMessages(currentSession) && !currentSession.archived : false;
  const statusTone = currentSession
    ? currentSession.archived
      ? "neutral"
      : pending
        ? "warning"
        : currentSession.governanceState === "Backend issue"
          ? "danger"
          : "success"
    : "neutral";

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

  const primaryStats = [
    { label: "Current model", value: currentSession.modelName, icon: "spark" },
    { label: "Governance", value: currentSession.governanceState, icon: "shield" },
    { label: "Messages", value: String(currentSession.messages.length), icon: "chat" },
  ];

  const systemSignals = [
    {
      label: "Connection",
      value: currentSession.governanceState === "Backend issue" ? "Attention needed" : "Connected",
      tone: currentSession.governanceState === "Backend issue" ? "danger" : "success",
    },
    {
      label: "Runtime",
      value: pending ? "Running" : "Idle",
      tone: pending ? "warning" : "neutral",
    },
    {
      label: "Governance",
      value: currentSession.governanceState,
      tone:
        currentSession.governanceState === "Artifacts generated"
          ? "success"
          : currentSession.governanceState === "Hook attempted" || currentSession.governanceState === "Hook armed"
            ? "warning"
            : currentSession.governanceState === "Backend issue"
              ? "danger"
              : "neutral",
    },
  ];

  return (
    <div className="app-shell">
      <div className="ambient ambient-left" />
      <div className="ambient ambient-right" />

      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">
            <Icon name="spark" />
          </div>
          <div>
            <span className="eyebrow">Kentro</span>
            <h1>Governance Workspace</h1>
            <p>Enterprise AI governance operations for policy summaries, release reviews, and artifact generation.</p>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Workspace navigation">
          {sidebarGroups.map((group) => (
            <section key={group.label} className="nav-group">
              <span className="nav-group-label">{group.label}</span>
              <div className="nav-list">
                {group.items.map((item) => (
                  <button key={item.label} type="button" className={`nav-item${item.active ? " nav-item-active" : ""}`}>
                    <span className="nav-item-icon">
                      <Icon name={item.icon} />
                    </span>
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </nav>

        <button type="button" className="primary-action" onClick={handleNewChat}>
          <Icon name="plus" />
          <span>New chat</span>
        </button>

        <label className="search-shell">
          <span className="search-label">Search chats</span>
          <span className="search-input-wrap">
            <span className="search-input-icon">
              <Icon name="search" />
            </span>
            <input
              type="text"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              placeholder="Search titles, prompts, runs, or metadata..."
            />
          </span>
        </label>

        <section className="sidebar-section">
          <div className="section-heading">
            <div>
              <span className="section-kicker">Workspace</span>
              <h2>System overview</h2>
            </div>
          </div>
          <div className="stats-grid">
            {primaryStats.map((stat) => (
              <StatCard key={stat.label} icon={stat.icon} label={stat.label} value={stat.value} />
            ))}
          </div>
        </section>

        <section className="sidebar-section sidebar-section-grow">
          <div className="section-heading">
            <div>
              <span className="section-kicker">Chats</span>
              <h2>Saved chats</h2>
            </div>
            <span className="section-count">{filteredActiveSessions.length}</span>
          </div>
          <div className="history-list premium-scroll">
            {filteredActiveSessions.length === 0 ? (
              <p className="history-empty">No active chats match this search.</p>
            ) : (
              filteredActiveSessions.map((session) => (
                <SessionCard
                  key={session.id}
                  session={session}
                  active={session.id === currentSession.id}
                  editing={editingSessionId === session.id}
                  titleDraft={titleDraft}
                  pendingDelete={pendingDeleteId === session.id}
                  onSelect={setCurrentSessionId}
                  onTitleDraftChange={setTitleDraft}
                  onRenameStart={startRenameSession}
                  onRenameCancel={cancelRenameSession}
                  onRenameSave={saveRenameSession}
                  onArchive={handleArchiveSession}
                  onDeleteAsk={confirmDeleteSession}
                  onDeleteCancel={cancelDeleteSession}
                  onDeleteConfirm={handleDeleteSession}
                />
              ))
            )}
          </div>
          <button type="button" className="secondary-action" onClick={() => setDownloadSessionId(currentSession.id)}>
            <Icon name="download" />
            <span>Download current chat</span>
          </button>
        </section>

        {archivedSessions.length > 0 ? (
          <section className="sidebar-section">
            <div className="section-heading">
              <div>
                <span className="section-kicker">Archive</span>
                <h2>Archived chats</h2>
              </div>
              <span className="section-count">{filteredArchivedSessions.length}</span>
            </div>
            <div className="history-list premium-scroll history-list-compact">
              {filteredArchivedSessions.length === 0 ? (
                <p className="history-empty">No archived chats match this search.</p>
              ) : (
                filteredArchivedSessions.map((session) => (
                  <SessionCard
                    key={session.id}
                    session={session}
                    active={session.id === currentSession.id}
                    archived
                    pendingDelete={pendingDeleteId === session.id}
                    onSelect={setCurrentSessionId}
                    onRestore={handleRestoreSession}
                    onDeleteAsk={confirmDeleteSession}
                    onDeleteCancel={cancelDeleteSession}
                    onDeleteConfirm={handleDeleteSession}
                  />
                ))
              )}
            </div>
          </section>
        ) : null}
      </aside>

      <main className="workspace">
        <header className="workspace-header">
          <div className="header-copy">
            <span className="eyebrow">Companion app</span>
            <h2>{currentSession.title}</h2>
            <p>{currentSession.statusText}</p>
          </div>
          <div className="header-status">
            <StatusBadge tone={statusTone}>
              {currentSession.archived ? "Archived" : pending ? "Running" : "Ready"}
            </StatusBadge>
            <div className="header-meta">
              <span>Model: {currentSession.modelName}</span>
              <span>{currentSession.archived ? "Read-only thread" : "Live operator workspace"}</span>
            </div>
          </div>
        </header>

        <section className="signal-bar">
          {systemSignals.map((signal) => (
            <SignalPill key={signal.label} label={signal.label} value={signal.value} tone={signal.tone} />
          ))}
        </section>

        <section className="workspace-topline">
          <div className="workspace-title-block">
            <span className="section-kicker">Operator thread</span>
            <h3>Governance execution surface</h3>
            <p>
              {currentSession.archived
                ? "This chat is archived. Restore it from the sidebar before sending new messages."
                : "Use the thread for concise governance questions, release checks, and policy summaries."}
            </p>
          </div>

          <div className="summary-grid">
            <InfoCard
              title="Session posture"
              value={currentSession.sessionPosture}
              detail="Operators can keep responses local or route them into governance artifact generation."
            />
            <InfoCard
              title="Last governance run"
              value={currentSession.lastArtifactRunId ? `Run ${currentSession.lastArtifactRunId}` : "No artifact run yet"}
              detail={currentSession.lastArtifactPath || "Generated outputs will appear here when the governance hook completes."}
            />
          </div>
        </section>

        <section className="chat-surface">
          <div className="chat-surface-frame">
            <div className="chat-toolbar">
              <div className="chat-toolbar-copy">
                <span className="section-kicker">Conversation</span>
                <strong>Operator conversation</strong>
              </div>
              <div className="chat-toolbar-actions">
                <span className="chat-toolbar-note">{currentSession.messages.length} messages in thread</span>
              </div>
            </div>

            <section className="conversation premium-scroll">
              {currentSession.messages.map((message, index) => (
                <div key={message.id} className="message-stack">
                  <MessageBubble message={message} />
                  {isEmptyState && index === 0 ? (
                    <div className="empty-state-panel">
                      <div className="empty-state-copy">
                        <span className="section-kicker">Start here</span>
                        <h3>Choose a strong first prompt</h3>
                        <p>Start with a policy summary, a release gate check, or a governance artifact preview.</p>
                      </div>
                      <div className="prompt-grid">
                        {onboardingPrompts.map((item) => (
                          <button key={item.title} type="button" className="prompt-card" onClick={() => setDraft(item.prompt)}>
                            <span className="prompt-card-icon">
                              <Icon name="spark" />
                            </span>
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
                  <div className="message-topline">
                    <div className="message-avatar">
                      <Icon name="spark" />
                    </div>
                    <div>
                      <div className="message-label">Assistant</div>
                      <div className="message-meta">Waiting for backend</div>
                    </div>
                  </div>
                  <p>Thinking through the local scaffold and governance handoff...</p>
                </article>
              ) : null}
              <div ref={scrollAnchorRef} />
            </section>
          </div>

          <form className="composer" onSubmit={handleSubmit}>
            <div className="composer-header">
              <div>
                <span className="section-kicker">Compose</span>
                <h3>Send a governance request</h3>
              </div>
              <div className="composer-hint">
                {currentSession.archived
                  ? "Archived chats are view-only."
                  : "Ask for policy summaries, control checks, release readiness, or artifact generation."}
              </div>
            </div>

            <div className="composer-shell">
              <textarea
                id="chat-input"
                rows="1"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                disabled={currentSession.archived}
                placeholder={
                  currentSession.archived
                    ? "This archived chat is read-only until restored..."
                    : "Try: Summarize the latest policy exception, list release blockers, or prepare governance-ready notes..."
                }
              />

              <div className="composer-footer">
                <p>
                  {currentSession.archived
                    ? "Restore the chat to continue the conversation."
                    : "Replies come from the local Express scaffold until a live model is connected."}
                </p>
                <button type="submit" className="send-button" disabled={currentSession.archived || pending || !draft.trim()}>
                  <span>{pending ? "Sending..." : "Send message"}</span>
                  <Icon name="send" />
                </button>
              </div>
            </div>
          </form>
        </section>
      </main>

      <div className="toast-stack">
        {toasts.map((toast) => (
          <div key={toast.id} className="toast">
            <span className="toast-indicator" />
            <span>{toast.message}</span>
          </div>
        ))}
      </div>

      {downloadSession ? (
        <div className="modal-backdrop" onClick={() => setDownloadSessionId("")}>
          <div className="download-modal" onClick={(event) => event.stopPropagation()}>
            <span className="section-kicker">Download chat</span>
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

function SessionCard({
  session,
  active = false,
  archived = false,
  editing = false,
  titleDraft = "",
  pendingDelete = false,
  onSelect,
  onTitleDraftChange,
  onRenameStart,
  onRenameCancel,
  onRenameSave,
  onArchive,
  onRestore,
  onDeleteAsk,
  onDeleteCancel,
  onDeleteConfirm,
}) {
  return (
    <div className={`history-item${active ? " history-item-active" : ""}${archived ? " history-item-archived" : ""}`}>
      {editing ? (
        <div className="history-main history-main-editing">
          <input
            className="history-title-input"
            value={titleDraft}
            onChange={(event) => onTitleDraftChange(event.target.value)}
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
        <button type="button" className="history-main" onClick={() => onSelect(session.id)}>
          <div className="history-title-row">
            <strong>{session.title}</strong>
            <span className={`mini-status mini-status-${statusToneForGovernance(session.governanceState)}`} />
          </div>
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
        {editing ? (
          <>
            <button type="button" className="history-save" onClick={() => onRenameSave(session.id)}>
              Save
            </button>
            <button type="button" className="history-cancel" onClick={onRenameCancel}>
              Cancel
            </button>
          </>
        ) : archived ? (
          <>
            <button type="button" className="history-restore" onClick={() => onRestore(session.id)}>
              Restore
            </button>
            {pendingDelete ? (
              <>
                <button type="button" className="history-confirm" onClick={() => onDeleteConfirm(session.id)}>
                  Confirm
                </button>
                <button type="button" className="history-cancel" onClick={onDeleteCancel}>
                  Cancel
                </button>
              </>
            ) : (
              <button type="button" className="history-delete" onClick={() => onDeleteAsk(session.id)}>
                Delete
              </button>
            )}
          </>
        ) : (
          <>
            <button type="button" className="history-rename" onClick={() => onRenameStart(session)}>
              Edit
            </button>
            <button type="button" className="history-archive" onClick={() => onArchive(session.id)}>
              Archive
            </button>
            {pendingDelete ? (
              <>
                <button type="button" className="history-confirm" onClick={() => onDeleteConfirm(session.id)}>
                  Confirm
                </button>
                <button type="button" className="history-cancel" onClick={onDeleteCancel}>
                  Cancel
                </button>
              </>
            ) : (
              <button type="button" className="history-delete" onClick={() => onDeleteAsk(session.id)}>
                Delete
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function StatCard({ icon, label, value }) {
  return (
    <div className="stat-card">
      <div className="stat-card-icon">
        <Icon name={icon} />
      </div>
      <div>
        <span className="stat-card-label">{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function InfoCard({ title, value, detail }) {
  return (
    <article className="info-card">
      <span className="section-kicker">{title}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function StatusBadge({ tone, children }) {
  return <div className={`status-badge status-badge-${tone}`}>{children}</div>;
}

function SignalPill({ label, value, tone }) {
  return (
    <div className={`signal-pill signal-pill-${tone}`}>
      <span className={`signal-dot signal-dot-${tone}`} />
      <span className="signal-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MessageBubble({ message }) {
  return (
    <article className={`message message-${message.role}`}>
      <div className="message-topline">
        <div className={`message-avatar message-avatar-${message.role}`}>
          <Icon name={message.role === "user" ? "person" : "spark"} />
        </div>
        <div>
          <div className="message-label">{message.meta?.label ?? message.role}</div>
          <div className="message-meta">{message.meta?.timestamp ?? timeLabel()}</div>
        </div>
      </div>
      <p>{message.content}</p>
    </article>
  );
}

function Icon({ name }) {
  switch (name) {
    case "plus":
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M10 4.167v11.666M4.167 10h11.666" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      );
    case "chat":
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M5.833 14.167 3.333 16.667V5.833A1.667 1.667 0 0 1 5 4.167h10A1.667 1.667 0 0 1 16.667 5.833v6.667A1.667 1.667 0 0 1 15 14.167H5.833Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      );
    case "archive":
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M3.333 5h13.334v2.5H3.333V5Zm1.25 4.167h10.834v6.25H4.583v-6.25Zm3.334 2.5h4.166" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "shield":
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M10 2.917 4.167 5.417v4.25c0 3.283 2.133 6.35 5.833 7.416 3.7-1.066 5.833-4.133 5.833-7.416v-4.25L10 2.917Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      );
    case "search":
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <circle cx="9.167" cy="9.167" r="4.583" stroke="currentColor" strokeWidth="1.5" />
          <path d="m12.5 12.5 3.333 3.333" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "download":
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M10 3.333v8.334m0 0 3.333-3.334M10 11.667 6.667 8.333M4.167 15.833h11.666" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "send":
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="m16.667 3.333-7.5 13.334-1.667-5-5-1.667 13.334-7.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      );
    case "person":
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="M10 10a3.333 3.333 0 1 0 0-6.667A3.333 3.333 0 0 0 10 10Zm-5 6.667c.689-2.153 2.809-3.75 5-3.75s4.311 1.597 5 3.75" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "spark":
    default:
      return (
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path d="m10 2.5 1.817 4.85L16.667 9.167l-4.85 1.816L10 15.833l-1.817-4.85L3.333 9.167l4.85-1.817L10 2.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      );
  }
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

function statusToneForGovernance(governanceState) {
  if (governanceState === "Artifacts generated") {
    return "success";
  }

  if (governanceState === "Hook attempted" || governanceState === "Hook armed") {
    return "warning";
  }

  if (governanceState === "Backend issue") {
    return "danger";
  }

  return "neutral";
}
