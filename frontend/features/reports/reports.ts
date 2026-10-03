import { api } from "@/lib/api";

export interface Period {
  id: string;
  label: string;
  start_date: string;
  end_date: string;
  framework_version_code: string | null;
  locked: boolean;
}

export interface ReportRow {
  id: string;
  period_id: string;
  snapshot_id: string;
  checksum: string | null;
  status: "PENDING" | "RUNNING" | "SUCCESS" | "FAILED";
  file_object_key: string | null;
  error: string | null;
  retry_count: number;
  created_at: string;
  completed_at: string | null;
}

export const listPeriods = () => api<Period[]>("/api/v1/reporting-periods");
export const lockPeriod = (id: string) =>
  api<Period>(`/api/v1/reporting-periods/${id}/lock`, { method: "POST" });
export const generateReport = (periodId: string) =>
  api<ReportRow>(`/api/v1/reports/${periodId}/generate`, { method: "POST" });
export const listReports = (periodId: string) =>
  api<ReportRow[]>(`/api/v1/reports/${periodId}`);
export const downloadReport = (periodId: string) =>
  api<{ url: string }>(`/api/v1/reports/${periodId}/download`);
