import { api } from "@/lib/api";

export interface FrameworkVersion {
  id: string;
  version_code: string;
  name: string;
  description: string | null;
  is_active: boolean;
  metric_count: number;
}

export interface MetricMeta {
  metric_code: string;
  section: string;
  principle: string | null;
  label: string;
  data_type: string;
  unit_family: string | null;
  allowed_units: string[] | null;
  canonical_unit: string | null;
  required: boolean;
  aggregation_semantics: string;
  ratio_numerator_code: string | null;
  ratio_denominator_code: string | null;
  evidence_required: boolean;
  brsr_core: boolean;
  display_order: number | null;
}

export interface ValidationRuleMeta {
  rule_code: string;
  rule_class: string;
  target_metric_code: string | null;
  severity: string;
  config: Record<string, unknown>;
  applies_on: string;
  version: number;
  message_template: string | null;
}

export interface FormulaMeta {
  code: string;
  name: string;
  description: string | null;
  versions: { version: number; expression: string; input_metric_codes: string[]; constants: Record<string, number> }[];
}

export const listVersions = () => api<FrameworkVersion[]>("/api/v1/framework/versions");
export const listMetrics = (versionId: string) =>
  api<MetricMeta[]>(`/api/v1/framework/versions/${versionId}/metrics`);
export const listRules = (versionId: string) =>
  api<ValidationRuleMeta[]>(`/api/v1/framework/versions/${versionId}/rules`);
export const listFormulas = (versionId: string) =>
  api<FormulaMeta[]>(`/api/v1/framework/versions/${versionId}/formulas`);
