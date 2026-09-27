"use client";

import { useEffect, useState } from "react";

import { MetricMeta } from "@/features/collection/collection";

export interface FormValue {
  raw_value: number | null;
  raw_unit: string | null;
  qualitative_value: string | null;
}

/**
 * THE dynamic metric form renderer.
 * Input controls are derived entirely from MetricDefinition metadata:
 * a metric added to the framework renders here with zero frontend changes.
 */
export function DynamicMetricForm({
  metric,
  initialValue,
  initialVersion,
  disabled,
  onSave,
}: {
  metric: MetricMeta;
  initialValue: FormValue;
  initialVersion: number | null;
  disabled: boolean;
  onSave: (value: FormValue, action: "SAVE_DRAFT" | "SUBMIT", expectedLastVersion: number | null) => Promise<void>;
}) {
  const [value, setValue] = useState<FormValue>(initialValue);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"draft" | "submit" | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    setValue(initialValue);
  }, [initialValue, initialVersion]);

  const units = metric.allowed_units ?? (metric.canonical_unit ? [metric.canonical_unit] : []);
  const isNumeric = metric.data_type === "numeric";
  const isCategorical = metric.data_type === "categorical";
  const isBoolean = metric.data_type === "boolean";

  async function submit(action: "SAVE_DRAFT" | "SUBMIT") {
    setError(null);
    setSuccess(null);
    if (action === "SUBMIT" && metric.required) {
      if (isNumeric && (value.raw_value === null || Number.isNaN(value.raw_value))) {
        setError("A numeric value is required before submitting");
        return;
      }
      if (!isNumeric && !value.qualitative_value) {
        setError("A response is required before submitting");
        return;
      }
    }
    setBusy(action === "SUBMIT" ? "submit" : "draft");
    try {
      await onSave(value, action, initialVersion);
      setSuccess(action === "SUBMIT" ? "Submitted for review" : "Draft saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="metric-form">
      <div className="metric-form-header">
        <h2>{metric.label}</h2>
        <div className="metric-flags">
          {metric.brsr_core && <span className="badge core">BRSR Core</span>}
          {metric.evidence_required && <span className="badge evidence">Evidence required</span>}
          {metric.required && <span className="badge required">Required</span>}
        </div>
      </div>
      {metric.description && <p className="hint">{metric.description}</p>}

      {isNumeric && (
        <div className="form-row">
          <label>
            Value
            <input
              type="number"
              value={value.raw_value ?? ""}
              disabled={disabled}
              onChange={(e) =>
                setValue({ ...value, raw_value: e.target.value === "" ? null : Number(e.target.value) })
              }
            />
          </label>
          {units.length > 0 && (
            <label>
              Unit
              <select
                value={value.raw_unit ?? units[0]}
                disabled={disabled}
                onChange={(e) => setValue({ ...value, raw_unit: e.target.value })}
              >
                {units.map((u) => (
                  <option key={u} value={u}>
                    {u}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      {metric.data_type === "qualitative" && (
        <label>
          Response
          <textarea
            rows={4}
            value={value.qualitative_value ?? ""}
            disabled={disabled}
            onChange={(e) => setValue({ ...value, qualitative_value: e.target.value })}
          />
        </label>
      )}

      {isCategorical && (
        <label>
          Selection
          <select
            value={value.qualitative_value ?? ""}
            disabled={disabled}
            onChange={(e) => setValue({ ...value, qualitative_value: e.target.value })}
          >
            <option value="">— select —</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
            <option value="partial">Partial</option>
          </select>
        </label>
      )}

      {isBoolean && (
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={value.qualitative_value === "true"}
            disabled={disabled}
            onChange={(e) =>
              setValue({ ...value, qualitative_value: e.target.checked ? "true" : "false" })
            }
          />
          Yes
        </label>
      )}

      {error && <div className="auth-error">{error}</div>}
      {success && <div className="form-success">{success}</div>}

      {!disabled && (
        <div className="form-actions">
          <button className="ghostbtn" disabled={busy !== null} onClick={() => submit("SAVE_DRAFT")}>
            {busy === "draft" ? "Saving…" : "Save draft"}
          </button>
          <button className="primarybtn" disabled={busy !== null} onClick={() => submit("SUBMIT")}>
            {busy === "submit" ? "Submitting…" : "Submit for review"}
          </button>
        </div>
      )}
    </div>
  );
}
