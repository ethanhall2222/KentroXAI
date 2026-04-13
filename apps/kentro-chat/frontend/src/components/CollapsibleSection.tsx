import { useState, type PropsWithChildren } from "react";
import { cn } from "../lib/utils";
import { Icon } from "./Icon";

export function CollapsibleSection({
  title,
  defaultOpen = false,
  children,
}: PropsWithChildren<{ title: string; defaultOpen?: boolean }>) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium text-slate-800"
      >
        <span>{title}</span>
        <Icon name="chevron" className={cn("h-4 w-4 transition", open && "rotate-90")} />
      </button>
      {open ? <div className="border-t border-slate-200 px-4 py-3 text-sm text-slate-600">{children}</div> : null}
    </section>
  );
}
