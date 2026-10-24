"use client";

import { useState } from "react";

import { CLAIM_TEMPLATES, PROVIDERS, type Source } from "../../../lib/accounts";

/** Reads the shared fact fields from a submitted form into an API body. */
export function factBody(form: FormData): { body?: Record<string, unknown>; error?: string } {
  let value: unknown;
  try {
    value = JSON.parse(String(form.get("value") ?? ""));
  } catch {
    return { error: "Claim value must be valid JSON" };
  }
  const toIso = (raw: FormDataEntryValue | null) => (raw ? new Date(String(raw)).toISOString() : undefined);
  const body: Record<string, unknown> = {
    claim_type: form.get("claim_type"),
    value,
    verification_status: form.get("verification_status"),
    confidence_label: form.get("confidence_label"),
    observed_at: toIso(form.get("observed_at")) ?? new Date().toISOString(),
  };
  const excerpt = String(form.get("evidence_excerpt") ?? "").trim();
  if (excerpt) body.evidence_excerpt = excerpt;
  const mode = form.get("source_mode");
  if (mode === "existing") {
    body.source = { source_id: form.get("source_id") };
  } else if (mode === "new") {
    const expires = toIso(form.get("source_expires_at"));
    const key = String(form.get("external_key") ?? "").trim();
    body.source = {
      new: {
        provider: form.get("provider"),
        source_url: String(form.get("source_url") ?? "").trim(),
        storage_class: form.get("storage_class"),
        observed_at: body.observed_at,
        ...(expires ? { expires_at: expires } : {}),
        ...(key ? { external_key: key } : {}),
      },
    };
  }
  return { body };
}

export default function FactFields({
  idPrefix,
  sources,
  claimType,
  fixedClaimType = false,
}: {
  idPrefix: string;
  sources: Source[];
  claimType?: string;
  fixedClaimType?: boolean;
}) {
  const [type, setType] = useState(claimType ?? "campus_count");
  const [value, setValue] = useState(JSON.stringify(CLAIM_TEMPLATES[type] ?? {}));
  const [mode, setMode] = useState<"none" | "existing" | "new">("none");

  return (
    <fieldset>
      <legend>Fact</legend>
      <p>
        <label htmlFor={`${idPrefix}-claim`}>Claim type</label>{" "}
        {fixedClaimType ? (
          <input id={`${idPrefix}-claim`} name="claim_type" value={type} readOnly />
        ) : (
          <select
            id={`${idPrefix}-claim`}
            name="claim_type"
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setValue(JSON.stringify(CLAIM_TEMPLATES[e.target.value] ?? {}));
            }}
          >
            {Object.keys(CLAIM_TEMPLATES).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        )}
      </p>
      <p>
        <label htmlFor={`${idPrefix}-value`}>Value (JSON)</label>{" "}
        <input id={`${idPrefix}-value`} name="value" value={value} onChange={(e) => setValue(e.target.value)} size={50} />
      </p>
      <p>
        <label htmlFor={`${idPrefix}-status`}>Verification</label>{" "}
        <select id={`${idPrefix}-status`} name="verification_status" defaultValue="hypothesis">
          <option value="hypothesis">Hypothesis (not verified)</option>
          <option value="source_supported">Source-supported (needs a source)</option>
        </select>{" "}
        <label htmlFor={`${idPrefix}-confidence`}>Confidence</label>{" "}
        <select id={`${idPrefix}-confidence`} name="confidence_label" defaultValue="weak">
          <option value="strong">strong</option>
          <option value="moderate">moderate</option>
          <option value="weak">weak</option>
          <option value="unknown">unknown</option>
        </select>
      </p>
      <p>
        <label htmlFor={`${idPrefix}-observed`}>Observed at (your local time)</label>{" "}
        <input id={`${idPrefix}-observed`} name="observed_at" type="datetime-local" />
      </p>
      <p>
        <label htmlFor={`${idPrefix}-excerpt`}>Evidence excerpt (needs full storage rights)</label>
        <br />
        <textarea id={`${idPrefix}-excerpt`} name="evidence_excerpt" maxLength={1000} rows={3} cols={60} />
      </p>
      <p role="radiogroup" aria-label="Source">
        Source:{" "}
        {(["none", "existing", "new"] as const).map((m) => (
          <label key={m}>
            <input type="radio" name="source_mode" value={m} checked={mode === m} onChange={() => setMode(m)} />{" "}
            {m === "none" ? "No source" : m === "existing" ? "Existing source" : "Register a source (not fetched)"}{" "}
          </label>
        ))}
      </p>
      {mode === "existing" ? (
        <p>
          <label htmlFor={`${idPrefix}-source`}>Source</label>{" "}
          <select id={`${idPrefix}-source`} name="source_id">
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.provider}: {s.source_url}
              </option>
            ))}
          </select>
        </p>
      ) : null}
      {mode === "new" ? (
        <>
          <p>
            <label htmlFor={`${idPrefix}-provider`}>Provider</label>{" "}
            <select id={`${idPrefix}-provider`} name="provider">
              {PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>{" "}
            <label htmlFor={`${idPrefix}-storage`}>Storage rights</label>{" "}
            <select id={`${idPrefix}-storage`} name="storage_class" defaultValue="metadata_only">
              <option value="metadata_only">metadata_only</option>
              <option value="derived_only">derived_only</option>
              <option value="full_allowed">full_allowed</option>
            </select>
          </p>
          <p>
            <label htmlFor={`${idPrefix}-url`}>Source URL</label>{" "}
            <input id={`${idPrefix}-url`} name="source_url" type="url" maxLength={2048} size={50} />
          </p>
          <p>
            <label htmlFor={`${idPrefix}-key`}>External key (optional)</label>{" "}
            <input id={`${idPrefix}-key`} name="external_key" maxLength={300} />{" "}
            <label htmlFor={`${idPrefix}-expires`}>Source expires (optional)</label>{" "}
            <input id={`${idPrefix}-expires`} name="source_expires_at" type="datetime-local" />
          </p>
        </>
      ) : null}
    </fieldset>
  );
}
