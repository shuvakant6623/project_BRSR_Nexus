import { api } from "@/lib/api";

export interface EvidenceRow {
  id: string;
  metric_value_id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  sha256_hash: string;
  uploaded_by: string;
  uploaded_at: string;
  is_deleted: boolean;
}

export const listEvidence = (metricValueId: string) =>
  api<EvidenceRow[]>(`/api/v1/evidence/by-value/${metricValueId}`);

export const uploadEvidence = (metricValueId: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api<EvidenceRow>(
    `/api/v1/evidence?metric_value_id=${metricValueId}`,
    { method: "POST", body: form },
  );
};

export const downloadEvidence = (id: string) =>
  api<{ url: string; expires_in_hours: number }>(`/api/v1/evidence/${id}/download`);

export const deleteEvidence = (id: string) =>
  api<void>(`/api/v1/evidence/${id}`, { method: "DELETE" });
