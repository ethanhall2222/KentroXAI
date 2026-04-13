import type { PropsWithChildren } from "react";
import { cn } from "../lib/utils";
import { Button } from "./Button";
import { Icon } from "./Icon";

export function Drawer({
  open,
  title,
  onClose,
  children,
}: PropsWithChildren<{ open: boolean; title: string; onClose: () => void }>) {
  return (
    <>
      <div
        className={cn(
          "fixed inset-0 z-30 bg-slate-950/20 transition",
          open ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={onClose}
      />
      <aside
        className={cn(
          "fixed right-0 top-0 z-40 flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-slate-50 shadow-2xl transition-transform duration-300",
          open ? "translate-x-0" : "translate-x-full",
        )}
        aria-hidden={!open}
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Insights</p>
            <h2 className="mt-1 text-lg font-semibold text-slate-900">{title}</h2>
          </div>
          <Button variant="subtle" className="rounded-xl px-3 py-2" onClick={onClose} aria-label="Close details panel">
            <Icon name="close" className="h-4 w-4" />
          </Button>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-5">{children}</div>
      </aside>
    </>
  );
}
