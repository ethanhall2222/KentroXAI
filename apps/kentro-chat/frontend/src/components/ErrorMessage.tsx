import { useState } from "react";
import { Button } from "./Button";
import { CollapsibleSection } from "./CollapsibleSection";

export function ErrorMessage({
  content,
  detail,
  onRetry,
}: {
  content: string;
  detail?: string;
  onRetry?: () => void;
}) {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div className="space-y-3">
      <p className="text-sm leading-7 text-rose-700">{content}</p>
      <div className="flex flex-wrap gap-2">
        {onRetry ? (
          <Button variant="subtle" className="rounded-xl bg-rose-50 text-rose-700 hover:bg-rose-100" onClick={onRetry}>
            Retry
          </Button>
        ) : null}
        {detail ? (
          <Button variant="ghost" className="rounded-xl" onClick={() => setShowDetails((value) => !value)}>
            {showDetails ? "Hide details" : "View details"}
          </Button>
        ) : null}
      </div>
      {detail && showDetails ? (
        <CollapsibleSection title="Error details" defaultOpen>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-slate-600">{detail}</pre>
        </CollapsibleSection>
      ) : null}
    </div>
  );
}
