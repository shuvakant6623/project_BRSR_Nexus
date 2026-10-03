import { api } from "@/lib/api";

export interface Contribution {
  entity_id: string;
  entity_name: string;
  value_id: string;
  value: number;
  unit: string;
  component?: string | null;
}

export interface TraceOut {
  entity_id: string;
  entity_name: string;
  metric_code: string;
  period_id: string;
  period_label: string;
  computed_value: number | null;
  unit: string | null;
  aggregation_semantics: string | null;
  is_stale: boolean;
  stale_reason: string | null;
  computed_at: string | null;
  contributing_value_count: number;
  contributions: Contribution[];
}

export interface RecomputeResult {
  status: string;
  consolidated: number;
  metrics: number;
  failures: { entity_name: string; metric_code: string; error: string }[];
}

export const getTrace = (entityId: string, metricCode: string, periodId: string) =>
  api<TraceOut>(`/api/v1/consolidation/${entityId}/${metricCode}/${periodId}`);

export const recomputeConsolidation = (periodId: string, metricCode?: string) =>
  api<RecomputeResult>("/api/v1/consolidation/recompute", {
    method: "POST",
    body: JSON.stringify({ period_id: periodId, metric_code: metricCode || null }),
  });
