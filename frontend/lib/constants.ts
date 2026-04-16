export const RESULT_COLORS: Record<string, { bg: string; text: string }> = {
  success: { bg: "bg-emerald-500/15", text: "text-emerald-400" },
  failure: { bg: "bg-red-500/15", text: "text-red-400" },
  partial: { bg: "bg-amber-500/15", text: "text-amber-400" },
  pending: { bg: "bg-zinc-500/15", text: "text-zinc-400" },
};

export const ACTION_TYPE_LABELS: Record<string, string> = {
  function_call: "Function Call",
  llm_call: "LLM Call",
  api_call: "API Call",
  decision: "Decision",
  tool_use: "Tool Use",
};

export const PERMISSION_COLORS: Record<string, string> = {
  read: "bg-sky-500/15 text-sky-400",
  write: "bg-emerald-500/15 text-emerald-400",
  admin: "bg-purple-500/15 text-purple-400",
};
