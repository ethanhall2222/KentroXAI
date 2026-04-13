export type GovernanceTone = "success" | "warning" | "danger" | "neutral";

export type MessageRole = "user" | "assistant";

export type MessageKind = "default" | "error";

export type ChatMessage = {
  id: string;
  role: MessageRole;
  content: string;
  meta?: {
    label?: string;
    timestamp?: string;
    kind?: MessageKind;
    detail?: string;
  };
  retryPrompt?: string;
};

export type ChatSession = {
  id: string;
  title: string;
  messages: ChatMessage[];
  modelName: string;
  lastModelUsed: string;
  governanceState: string;
  sessionPosture: string;
  statusText: string;
  archived: boolean;
  lastArtifactPath: string;
  lastArtifactRunId: string;
  lastScorecardUrl: string;
  lastScorecardHtmlPath: string;
  lastScorecardJsonPath: string;
  lastTrustScore: number | null;
  lastTrustScoreSource: string;
  lastOverallStatus: string;
  lastGoNoGo: string;
  lastEvidenceCompleteness: number | null;
  updatedAt: number;
};
