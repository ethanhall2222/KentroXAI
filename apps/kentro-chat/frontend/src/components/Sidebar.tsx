import { useState } from "react";
import type { ChatSession } from "../types";
import { cn, formatSessionTime, formatTrustScoreValue, statusToneForGovernance } from "../lib/utils";
import { Button } from "./Button";
import { Icon } from "./Icon";

export function Sidebar({
  sessions,
  archivedSessions,
  activeSessionId,
  searchQuery,
  onSearchChange,
  onSelectSession,
  onNewChat,
  onArchive,
  onRestore,
  onDelete,
  onRename,
}: {
  sessions: ChatSession[];
  archivedSessions: ChatSession[];
  activeSessionId: string;
  searchQuery: string;
  onSearchChange: (value: string) => void;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onArchive: (id: string) => void;
  onRestore: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (session: ChatSession) => void;
}) {
  return (
    <aside className="flex h-[calc(100vh-2rem)] flex-col rounded-[28px] border border-slate-200 bg-white/85 p-4 shadow-sm backdrop-blur">
      <div className="mb-4 flex items-center gap-3 px-2">
        <div className="grid h-10 w-10 place-items-center rounded-2xl bg-kentro-100 text-kentro-700">
          <Icon name="spark" className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Kentro</p>
          <h1 className="truncate text-base font-semibold text-slate-900">Kentro Chat</h1>
        </div>
      </div>

      <Button variant="primary" fullWidth onClick={onNewChat} className="mb-4 rounded-2xl">
        <Icon name="plus" className="h-4 w-4" />
        New Chat
      </Button>

      <label className="relative mb-4 block">
        <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="text"
          value={searchQuery}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Search"
          className="w-full rounded-2xl border border-slate-200 bg-slate-50 py-3 pl-11 pr-4 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-kentro-300 focus:ring-2 focus:ring-kentro-100"
        />
      </label>

      <div className="flex-1 overflow-y-auto pr-1">
        <ChatList
          title="Chats"
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={onSelectSession}
          onArchive={onArchive}
          onDelete={onDelete}
          onRename={onRename}
        />

        {archivedSessions.length > 0 ? (
          <ChatList
            title="Archived"
            sessions={archivedSessions}
            activeSessionId={activeSessionId}
            onSelectSession={onSelectSession}
            onRestore={onRestore}
            onDelete={onDelete}
            archived
          />
        ) : null}
      </div>
    </aside>
  );
}

function ChatList({
  title,
  sessions,
  activeSessionId,
  archived = false,
  onSelectSession,
  onArchive,
  onRestore,
  onDelete,
  onRename,
}: {
  title: string;
  sessions: ChatSession[];
  activeSessionId: string;
  archived?: boolean;
  onSelectSession: (id: string) => void;
  onArchive?: (id: string) => void;
  onRestore?: (id: string) => void;
  onDelete: (id: string) => void;
  onRename?: (session: ChatSession) => void;
}) {
  return (
    <section className="mb-4">
      <div className="mb-2 flex items-center justify-between px-2">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{title}</p>
        <span className="text-xs text-slate-400">{sessions.length}</span>
      </div>
      <div className="space-y-1">
        {sessions.length === 0 ? (
          <p className="px-2 py-3 text-sm text-slate-400">No chats yet.</p>
        ) : (
          sessions.map((session) => (
            <ChatHistoryItem
              key={session.id}
              session={session}
              active={session.id === activeSessionId}
              archived={archived}
              onSelect={() => onSelectSession(session.id)}
              onArchive={onArchive ? () => onArchive(session.id) : undefined}
              onRestore={onRestore ? () => onRestore(session.id) : undefined}
              onDelete={() => onDelete(session.id)}
              onRename={onRename ? () => onRename(session) : undefined}
            />
          ))
        )}
      </div>
    </section>
  );
}

function ChatHistoryItem({
  session,
  active,
  archived,
  onSelect,
  onArchive,
  onRestore,
  onDelete,
  onRename,
}: {
  session: ChatSession;
  active: boolean;
  archived: boolean;
  onSelect: () => void;
  onArchive?: () => void;
  onRestore?: () => void;
  onDelete: () => void;
  onRename?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const tone = statusToneForGovernance(session.governanceState);

  return (
    <div
      className={cn(
        "group relative rounded-2xl transition",
        active ? "bg-slate-100" : "hover:bg-slate-50",
      )}
    >
      <button type="button" onClick={onSelect} className="flex w-full items-start gap-3 px-3 py-3 text-left">
        <span
          className={cn(
            "mt-1 h-2.5 w-2.5 shrink-0 rounded-full",
            tone === "success" && "bg-emerald-500",
            tone === "warning" && "bg-amber-500",
            tone === "danger" && "bg-rose-500",
            tone === "neutral" && "bg-slate-300",
          )}
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-800">{session.title}</p>
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <span>{session.lastModelUsed || session.modelName}</span>
            <span>•</span>
            <span>{formatSessionTime(session.updatedAt)}</span>
          </div>
          {session.lastTrustScore !== null && session.lastTrustScore !== undefined ? (
            <p className="mt-1 text-xs text-slate-500">Trust {formatTrustScoreValue(session.lastTrustScore)}</p>
          ) : null}
        </div>
      </button>

      <button
        type="button"
        aria-label="Open chat actions"
        className="absolute right-2 top-2 rounded-xl p-2 text-slate-400 opacity-0 transition hover:bg-white hover:text-slate-700 group-hover:opacity-100 focus-visible:opacity-100"
        onClick={() => setMenuOpen((value) => !value)}
      >
        <Icon name="menu" className="h-4 w-4" />
      </button>

      {menuOpen ? (
        <div className="absolute right-2 top-11 z-20 min-w-[10rem] rounded-2xl border border-slate-200 bg-white p-1 shadow-xl">
          {!archived && onRename ? (
            <MenuAction
              label="Rename"
              onClick={() => {
                setMenuOpen(false);
                onRename();
              }}
            />
          ) : null}
          {!archived && onArchive ? (
            <MenuAction
              label="Archive"
              onClick={() => {
                setMenuOpen(false);
                onArchive();
              }}
            />
          ) : null}
          {archived && onRestore ? (
            <MenuAction
              label="Restore"
              onClick={() => {
                setMenuOpen(false);
                onRestore();
              }}
            />
          ) : null}
          <MenuAction
            label="Delete"
            danger
            onClick={() => {
              setMenuOpen(false);
              onDelete();
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

function MenuAction({
  label,
  danger = false,
  onClick,
}: {
  label: string;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full rounded-xl px-3 py-2 text-left text-sm transition",
        danger ? "text-rose-600 hover:bg-rose-50" : "text-slate-700 hover:bg-slate-50",
      )}
    >
      {label}
    </button>
  );
}
