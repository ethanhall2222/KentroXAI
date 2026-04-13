import type { PropsWithChildren } from "react";
import { cn } from "../lib/utils";
import { Button } from "./Button";
import { Icon } from "./Icon";

export function Modal({
  open,
  title,
  onClose,
  children,
}: PropsWithChildren<{ open: boolean; title: string; onClose: () => void }>) {
  return (
    <div
      className={cn(
        "fixed inset-0 z-50 grid place-items-center bg-slate-950/30 p-4 transition",
        open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
      )}
      onClick={onClose}
      aria-hidden={!open}
    >
      <div
        className={cn(
          "flex h-[min(88vh,840px)] w-full max-w-5xl flex-col overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-2xl transition",
          open ? "translate-y-0 scale-100" : "translate-y-4 scale-[0.98]",
        )}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Scorecard</p>
            <h2 className="mt-1 text-lg font-semibold text-slate-900">{title}</h2>
          </div>
          <Button variant="subtle" className="rounded-xl px-3 py-2" onClick={onClose} aria-label="Close scorecard">
            <Icon name="close" className="h-4 w-4" />
          </Button>
        </header>
        <div className="flex-1 overflow-hidden">{children}</div>
      </div>
    </div>
  );
}
