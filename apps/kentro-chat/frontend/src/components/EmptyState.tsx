import { Button } from "./Button";

export function EmptyState({
  prompts,
  onPromptSelect,
}: {
  prompts: Array<{ title: string; prompt: string }>;
  onPromptSelect: (prompt: string) => void;
}) {
  return (
    <div className="flex min-h-[55vh] flex-col items-center justify-center px-4 py-10 text-center">
      <div className="w-full max-w-3xl space-y-6">
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Kentro Chat</p>
          <h2 className="mx-auto max-w-2xl text-balance text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
            Ask about policy, governance, or release readiness.
          </h2>
          <p className="mx-auto max-w-2xl text-balance text-base leading-7 text-slate-600">
            Start with a simple question. Trust scoring, backend details, and governance metadata stay out of the way until you need them.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          {prompts.map((item) => (
            <Button
              key={item.title}
              variant="ghost"
              className="flex h-full flex-col items-start gap-2 rounded-3xl p-5 text-left"
              onClick={() => onPromptSelect(item.prompt)}
            >
              <span className="text-sm font-semibold text-slate-900">{item.title}</span>
              <span className="whitespace-normal text-sm leading-6 text-slate-600">{item.prompt}</span>
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
