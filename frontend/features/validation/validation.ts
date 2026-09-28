import { api } from "@/lib/api";

export interface ValidationException {
  id: string;
  rule_code: string;
  rule_version: number;
  severity: "BLOCKING" | "WARNING" | "INFO";
  message: string;
  entity_id: string;
  metric_code: string | null;
  period_id: string | null;
  assignment_id: string | null;
  observed_value: number | null;
  status: "OPEN" | "EXPLAINED" | "RESOLVED";
  explanation: string | null;
  created_at: string;
}

export const listExceptions = (params: Record<string, string> = {}) => {
  const qs = new URLSearchParams(params).toString();
  return api<ValidationException[]>(`/api/v1/validation/exceptions${qs ? `?${qs}` : ""}`);
};

export const runValidation = (periodId: string, entityId?: string) =>
  api<{ status: string; assignments: number; raised: number; auto_resolved: number; blocking: number }>(
    "/api/v1/validation/run",
    { method: "POST", body: JSON.stringify({ period_id: periodId, entity_id: entityId }) }
  );

export const explainException = (id: string, explanation: string) =>
  api<ValidationException>(`/api/v1/validation/exceptions/${id}/explain`, {
    method: "POST",
    body: JSON.stringify({ explanation }),
  });

export const resolveException = (id: string) =>
  api<ValidationException>(`/api/v1/validation/exceptions/${id}/resolve`, { method: "POST" });

export const SEVERITY_COLORS: Record<string, string> = {
  BLOCKING: "#ef4444",
  WARNING: "#f59e0b",
  INFO: "#38bdf8",
};

export const EXCEPTION_STATUS_COLORS: Record<string, string> = {
  OPEN: "#ef4444",
  EXPLAINED: "#f59e0b",
  RESOLVED: "#10b981",
};
