import { api, getAccessToken } from "@/lib/api";

export interface AssuranceIndicator {
  metric_code: string;
  label: string;
  principle: string | null;
  section: string;
  brsr_core: boolean;
  is_approved: boolean;
  has_evidence: boolean;
  has_blocking_exception: boolean;
  is_consolidated: boolean;
  is_ready: boolean;
  defects: string[];
}

export interface EntitySummary {
  entity_id: string;
  entity_name: string;
  total_indicators: number;
  approved_indicators: number;
  has_missing_evidence: boolean;
  has_blocking_exceptions: boolean;
  is_ready: boolean;
}

export interface AssuranceReadiness {
  period_id: string;
  period_label: string;
  is_locked: boolean;
  readiness_status: "READY" | "PROVISIONAL" | "NOT_READY";
  readiness_score_pct: number;
  score_explanation: string;
  total_indicators: number;
  ready_indicators: number;
  approved_indicators: number;
  missing_evidence_count: number;
  blocking_exception_count: number;
  incomplete_consolidation_count: number;
  entity_summaries: EntitySummary[];
  indicators: AssuranceIndicator[];
}

export async function getAssuranceReadiness(
  periodId?: string,
  brsrCoreOnly: boolean = false
): Promise<AssuranceReadiness> {
  const params = new URLSearchParams();
  if (periodId) params.set("period_id", periodId);
  if (brsrCoreOnly) params.set("brsr_core_only", "true");
  const qs = params.toString() ? `?${params.toString()}` : "";
  return api<AssuranceReadiness>(`/api/v1/assurance/readiness${qs}`);
}

export async function exportAssuranceReadinessCsv(
  periodId?: string,
  brsrCoreOnly: boolean = false
): Promise<void> {
  const params = new URLSearchParams();
  if (periodId) params.set("period_id", periodId);
  if (brsrCoreOnly) params.set("brsr_core_only", "true");
  const token = getAccessToken();
  if (token) params.set("token", token);
  const qs = params.toString() ? `?${params.toString()}` : "";
  
  const res = await fetch(`/api/v1/assurance/export${qs}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error(`Export failed: ${res.statusText}`);
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `assurance_readiness_${periodId || "period"}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}
