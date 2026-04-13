import type { RefObject } from "react";
import { EmptyState } from "./EmptyState";
import { MessageBubble } from "./MessageBubble";
import type { ChatMessage } from "../types";

export function ChatContainer({
  empty,
  messages,
  pending,
  prompts,
  onPromptSelect,
  onRetry,
  scrollAnchorRef,
}: {
  empty: boolean;
  messages: ChatMessage[];
  pending: boolean;
  prompts: Array<{ title: string; prompt: string }>;
  onPromptSelect: (prompt: string) => void;
  onRetry: (prompt: string) => void;
  scrollAnchorRef: RefObject<HTMLDivElement | null>;
}) {
  if (empty) {
    return <EmptyState prompts={prompts} onPromptSelect={onPromptSelect} />;
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} onRetry={onRetry} />
      ))}

      {pending ? (
        <MessageBubble
          message={{
            id: "pending",
            role: "assistant",
            content: "Running the Databricks governance job and waiting for the result...",
            meta: {
              label: "Kentro",
              timestamp: "Working...",
            },
          }}
        />
      ) : null}

      <div ref={scrollAnchorRef} />
    </div>
  );
}
