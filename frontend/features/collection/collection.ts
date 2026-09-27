import { api } from "@/lib/api";

export interface Assignment {
  id: string;
  metric_code: string;
  entity_id: string;
  period_id: string;
  owner_user_id: string;
  status: string;
  due_date: string | null;
}

export interface MetricMeta {
  metric_code: string;
  label: string;
  description: string | null;
  data_type: string;
  unit_family: string | null;
  allowed_units: string[] | null;
  canonical_unit: string | null;
  required: boolean;
  evidence_required: boolean;
  brsr_core: boolean;
  section: string;
  principle: string | null;
}

export interface ValueRow {
  id: string;
  version: number;
  raw_value: number | null;
  raw_unit: string | null;
  normalized_value: number | null;
  normalized_unit: string | null;
  qualitative_value: string | null;
  status: string;
  submitted_at: string | null;
}

export interface AssignmentDetail {
  assignment: Assignment;
  entity_name: string;
  period_label: string;
  metric: MetricMeta;
  values: ValueRow[];
  latest_version: number | null;
}

export interface SaveValueBody {
  action: "SAVE_DRAFT" | "SUBMIT";
  raw_value?: number | null;
  raw_unit?: string | null;
  qualitative_value?: string | null;
  expected_last_version?: number | null;
}

export const listAssignments = (params: Record<string, string> = {}) => {
  const qs = new URLSearchParams(params).toString();
  return api<Assignment[]>(`/api/v1/assignments${qs ? `?${qs}` : ""}`);
};

export const getAssignment = (id: string) =>
  api<AssignmentDetail>(`/api/v1/assignments/${id}`);

export const saveValue = (id: string, body: SaveValueBody) =>
  api<ValueRow>(`/api/v1/assignments/${id}/value`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const reviewAssignment = (id: string, action: string, comment?: string) =>
  api<Assignment>(`/api/v1/assignments/${id}/review`, {
    method: "POST",
    body: JSON.stringify({ action, comment }),
  });

export const STATUS_COLORS: Record<string, string> = {
  NOT_STARTED: "#94a3b8",
  IN_PROGRESS: "#38bdf8",
  SUBMITTED: "#a78bfa",
  UNDER_REVIEW: "#f59e0b",
  APPROVED: "#10b981",
  LOCKED: "#10b981",
  NEEDS_CORRECTION: "#f97316",
  REJECTED: "#ef4444",
};
