import type { ChatMessage } from "../types";
import { cn } from "../lib/utils";
import { ErrorMessage } from "./ErrorMessage";
import { Icon } from "./Icon";

export function MessageBubble({
  message,
  onRetry,
}: {
  message: ChatMessage;
  onRetry?: (prompt: string) => void;
}) {
  const isUser = message.role === "user";
  const isError = message.meta?.kind === "error";

  return (
    <article
      className={cn(
        "group rounded-3xl px-5 py-4 shadow-sm transition",
        isUser
          ? "ml-auto max-w-2xl bg-kentro-50 text-slate-900"
          : "max-w-3xl bg-white text-slate-900",
        isError && "border border-rose-200 bg-rose-50",
      )}
    >
      <div className="mb-2 flex items-center gap-3">
        <div
          className={cn(
            "grid h-8 w-8 place-items-center rounded-2xl",
            isUser ? "bg-slate-200 text-slate-700" : isError ? "bg-rose-100 text-rose-700" : "bg-kentro-100 text-kentro-700",
          )}
        >
          <Icon name={isUser ? "person" : "spark"} className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-900">{message.meta?.label ?? (isUser ? "You" : "Kentro")}</p>
          <p className="text-xs text-slate-500">{message.meta?.timestamp}</p>
        </div>
      </div>

      {isError ? (
        <ErrorMessage
          content={message.content}
          detail={message.meta?.detail}
          onRetry={message.retryPrompt && onRetry ? () => onRetry(message.retryPrompt!) : undefined}
        />
      ) : (
        <p className="whitespace-pre-wrap text-[15px] leading-7 text-slate-800">{message.content}</p>
      )}
    </article>
  );
}
