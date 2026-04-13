import type { FormEvent } from "react";
import { Button } from "./Button";
import { Icon } from "./Icon";

export function InputBar({
  draft,
  disabled,
  pending,
  onChange,
  onSubmit,
  onOpenScorecard,
}: {
  draft: string;
  disabled: boolean;
  pending: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onOpenScorecard: () => void;
}) {
  return (
    <form onSubmit={onSubmit} className="sticky bottom-0 z-10 border-t border-slate-200/80 bg-slate-50/90 px-4 py-4 backdrop-blur sm:px-6">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <Button variant="subtle" className="rounded-full px-4 py-2 text-sm" type="button" onClick={onOpenScorecard}>
            Generate Scorecard
          </Button>
          <p className="hidden text-xs text-slate-500 sm:block">
            Keep the prompt focused. Details and backend metadata live in the insights drawer.
          </p>
        </div>
        <div className="flex items-end gap-3 rounded-[28px] border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <textarea
            rows={1}
            value={draft}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            placeholder={disabled ? "This chat is archived." : "Message Kentro..."}
            className="max-h-48 min-h-[28px] flex-1 resize-none bg-transparent text-[15px] leading-7 text-slate-900 outline-none placeholder:text-slate-400"
          />
          <Button
            variant="primary"
            type="submit"
            disabled={disabled || pending || !draft.trim()}
            className="shrink-0 rounded-full px-4 py-3"
            aria-label={pending ? "Sending message" : "Send message"}
          >
            <span className="hidden sm:inline">{pending ? "Sending" : "Send"}</span>
            <Icon name="send" className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </form>
  );
}
