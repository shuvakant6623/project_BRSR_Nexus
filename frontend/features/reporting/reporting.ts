import { api } from "@/lib/api";

export interface ReportingPeriod {
  id: string;
  label: string;
  start_date: string;
  end_date: string;
  locked: boolean;
  framework_version_id: string;
}

export const listPeriods = () => api<ReportingPeriod[]>("/api/v1/reporting-periods");
