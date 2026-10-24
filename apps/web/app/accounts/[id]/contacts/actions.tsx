"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { karachiTime } from "../../../../lib/accounts";
import type { CampaignSummary } from "../../../../lib/campaigns";
import {
  CAPTURE_METHODS,
  CONTACT_ROLES,
  type Decision,
  karachiInputToIso,
  type Permission,
  type PolicyInfo,
  PROOF_KINDS,
  SUPPRESSION_REASONS,
} from "../../../../lib/contacts";
import { newKey } from "../../../../lib/discovery";
import { errorMessage, postJson } from "../../../../lib/mutate";

function useRun() {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function run(call: () => Promise<{ ok: boolean; data: unknown }>, success: string) {
    setPending(true);
    setMessage(null);
    try {
      const result = await call();
      setMessage(result.ok ? success : errorMessage(result.data));
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return { message, pending, run };
}

function Status({ message }: { message: string | null }) {
  return (
    <span role="status" aria-live="polite">
      {message}
    </span>
  );
}

export function AddContact({ accountId }: { accountId: string }) {
  const { message, pending, run } = useRun();
  const [address, setAddress] = useState("");
  const [role, setRole] = useState<string>("school_office");
  return (
    <form aria-label="Add contact" onSubmit={(e) => e.preventDefault()}>
      <label htmlFor="contact-address">WhatsApp number</label>{" "}
      <input id="contact-address" value={address} onChange={(e) => setAddress(e.target.value)} autoComplete="off" maxLength={32} />{" "}
      <label htmlFor="contact-role">Role</label>{" "}
      <select id="contact-role" value={role} onChange={(e) => setRole(e.target.value)}>
        {CONTACT_ROLES.map((r) => (
          <option key={r} value={r}>
            {r.replaceAll("_", " ")}
          </option>
        ))}
      </select>{" "}
      <button
        type="button"
        disabled={pending || address.trim().length < 8}
        onClick={() => run(() => postJson(`/api/v1/accounts/${accountId}/contacts`, { address, role, idempotency_key: newKey("contact") }), "Contact added (stored masked)")}
      >
        Add contact
      </button>{" "}
      <Status message={message} />
    </form>
  );
}

export function RecordEvidence({ contactId, wording, businessName }: { contactId: string; wording: Record<string, string>; businessName: string }) {
  const { message, pending, run } = useRun();
  const [purpose, setPurpose] = useState<"marketing" | "utility">("marketing");
  const [method, setMethod] = useState<string>(CAPTURE_METHODS[0]);
  const [proofKind, setProofKind] = useState<string>(PROOF_KINDS[0]);
  const [reference, setReference] = useState("");
  const [captured, setCaptured] = useState("");
  const [business, setBusiness] = useState(businessName);
  const ready = reference.trim().length >= 4 && captured.length >= 16;
  return (
    <form aria-label="Record opt-in evidence" onSubmit={(e) => e.preventDefault()}>
      <fieldset>
        <legend>Record opt-in evidence (pending until an owner verifies it)</legend>
        <label htmlFor={`purpose-${contactId}`}>Purpose</label>{" "}
        <select id={`purpose-${contactId}`} value={purpose} onChange={(e) => setPurpose(e.target.value as "marketing" | "utility")}>
          <option value="marketing">marketing</option>
          <option value="utility">utility</option>
        </select>{" "}
        <label htmlFor={`business-${contactId}`}>Business named in the opt-in</label>{" "}
        <input id={`business-${contactId}`} value={business} onChange={(e) => setBusiness(e.target.value)} maxLength={120} />{" "}
        <label htmlFor={`method-${contactId}`}>Capture method</label>{" "}
        <select id={`method-${contactId}`} value={method} onChange={(e) => setMethod(e.target.value)}>
          {CAPTURE_METHODS.map((m) => (
            <option key={m} value={m}>
              {m.replaceAll("_", " ")}
            </option>
          ))}
        </select>{" "}
        <label htmlFor={`proof-kind-${contactId}`}>Proof kind</label>{" "}
        <select id={`proof-kind-${contactId}`} value={proofKind} onChange={(e) => setProofKind(e.target.value)}>
          {PROOF_KINDS.map((k) => (
            <option key={k} value={k}>
              {k.replaceAll("_", " ")}
            </option>
          ))}
        </select>{" "}
        <label htmlFor={`proof-ref-${contactId}`}>Proof reference</label>{" "}
        <input id={`proof-ref-${contactId}`} value={reference} onChange={(e) => setReference(e.target.value)} maxLength={120} autoComplete="off" />{" "}
        <label htmlFor={`captured-${contactId}`}>Opt-in given at (Asia/Karachi)</label>{" "}
        <input id={`captured-${contactId}`} type="datetime-local" value={captured} onChange={(e) => setCaptured(e.target.value)} />{" "}
        <span>Consent wording: {wording[purpose]}</span>{" "}
        <button
          type="button"
          disabled={pending || !ready}
          onClick={() =>
            run(
              () =>
                postJson(`/api/v1/contacts/${contactId}/permissions`, {
                  purpose,
                  business_name: business,
                  capture_method: method,
                  consent_wording_version: wording[purpose],
                  proof_kind: proofKind,
                  proof_reference: reference,
                  captured_at: karachiInputToIso(captured),
                  idempotency_key: newKey("evidence"),
                }),
              "Evidence recorded as pending",
            )
          }
        >
          Record evidence
        </button>{" "}
        <Status message={message} />
      </fieldset>
    </form>
  );
}

export function PermissionActions({ contactId, permission, isOwner }: { contactId: string; permission: Permission; isOwner: boolean }) {
  const { message, pending, run } = useRun();
  const [reason, setReason] = useState("");
  const base = `/api/v1/contacts/${contactId}/permissions/${permission.id}`;
  const open = permission.status === "pending" || permission.status === "verified";
  if (!open) return null;
  const review = (decision: "verified" | "rejected") =>
    run(() => postJson(`${base}/verify`, { decision, reason, expected_version: permission.version, idempotency_key: newKey("review") }), `Evidence ${decision}`);
  return (
    <>
      <label htmlFor={`reason-${permission.id}`}>Reason ({permission.purpose})</label>{" "}
      <input id={`reason-${permission.id}`} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />{" "}
      {isOwner && permission.status === "pending" ? (
        <>
          <button type="button" disabled={pending || reason.trim().length < 3} onClick={() => review("verified")}>
            Verify evidence
          </button>{" "}
          <button type="button" disabled={pending || reason.trim().length < 3} onClick={() => review("rejected")}>
            Reject evidence
          </button>{" "}
        </>
      ) : null}
      <button
        type="button"
        disabled={pending || reason.trim().length < 3}
        onClick={() => run(() => postJson(`${base}/revoke`, { reason, expected_version: permission.version, idempotency_key: newKey("revoke") }), "Permission revoked")}
      >
        Revoke permission
      </button>{" "}
      <Status message={message} />
    </>
  );
}

export function Suppress({ contactId }: { contactId: string }) {
  const { message, pending, run } = useRun();
  const [reason, setReason] = useState<string>("opt_out");
  return (
    <p>
      <label htmlFor={`suppress-${contactId}`}>Suppression reason</label>{" "}
      <select id={`suppress-${contactId}`} value={reason} onChange={(e) => setReason(e.target.value)}>
        {SUPPRESSION_REASONS.map((r) => (
          <option key={r} value={r}>
            {r.replaceAll("_", " ")}
          </option>
        ))}
      </select>{" "}
      <button type="button" disabled={pending} onClick={() => run(() => postJson(`/api/v1/contacts/${contactId}/suppress`, { reason, idempotency_key: newKey("suppress") }), "Number suppressed")}>
        Suppress number
      </button>{" "}
      <Status message={message} />
    </p>
  );
}

export function Evaluate({ contactId, campaigns, fixtures }: { contactId: string; campaigns: CampaignSummary[]; fixtures: PolicyInfo["fixtures"] }) {
  const [purpose, setPurpose] = useState("marketing");
  const [campaign, setCampaign] = useState("");
  const [template, setTemplate] = useState("");
  const [inbound, setInbound] = useState("");
  const [result, setResult] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function check() {
    setPending(true);
    setError(null);
    try {
      const body: Record<string, string> = { contact_id: contactId, purpose };
      if (campaign) body.campaign_id = campaign;
      if (template) body.template_ref = template;
      if (inbound) body.inbound_ref = inbound;
      const response = await postJson("/api/v1/channel-eligibility/evaluate", body);
      if (response.ok) setResult(response.data as Decision);
      else setError(errorMessage(response.data));
    } finally {
      setPending(false);
    }
  }
  return (
    <section aria-label="Eligibility check">
      <h3>Check eligibility (simulation)</h3>
      <label htmlFor={`eval-purpose-${contactId}`}>Purpose</label>{" "}
      <select id={`eval-purpose-${contactId}`} value={purpose} onChange={(e) => setPurpose(e.target.value)}>
        <option value="marketing">marketing</option>
        <option value="utility">utility</option>
        <option value="service_reply">service reply</option>
      </select>{" "}
      <label htmlFor={`eval-campaign-${contactId}`}>Campaign</label>{" "}
      <select id={`eval-campaign-${contactId}`} value={campaign} onChange={(e) => setCampaign(e.target.value)}>
        <option value="">(none)</option>
        {campaigns.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>{" "}
      <label htmlFor={`eval-template-${contactId}`}>Template</label>{" "}
      <select id={`eval-template-${contactId}`} value={template} onChange={(e) => setTemplate(e.target.value)}>
        <option value="">(none)</option>
        {fixtures.templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.id} (synthetic fixture: {t.category}, {t.provider_status})
          </option>
        ))}
      </select>{" "}
      <label htmlFor={`eval-inbound-${contactId}`}>Inbound message</label>{" "}
      <select id={`eval-inbound-${contactId}`} value={inbound} onChange={(e) => setInbound(e.target.value)}>
        <option value="">(none)</option>
        {fixtures.inbound.map((m) => (
          <option key={m.id} value={m.id}>
            {m.id} (synthetic fixture, {m.text_kind})
          </option>
        ))}
      </select>{" "}
      <button type="button" disabled={pending} onClick={check}>
        Check eligibility
      </button>{" "}
      <span role="status" aria-live="polite">
        {error}
      </span>
      {result ? (
        <div role="region" aria-label="Eligibility result">
          <p>
            <strong>Decision: {result.decision.replaceAll("_", " ")}</strong> — live send authorized: no
          </p>
          {result.reasons.length > 0 ? (
            <ul aria-label="Why">
              {result.reasons.map((r) => (
                <li key={r.code}>
                  {r.code}: {r.explanation}
                </li>
              ))}
            </ul>
          ) : (
            <p>No blocking reason at {karachiTime(result.evaluated_at)}. This is not permission to send.</p>
          )}
          {result.next_window_at ? <p>Earliest window: {karachiTime(result.next_window_at)}</p> : null}
          <p>
            Policy {result.policy_version}; permission {result.permission_revision ? `v${result.permission_revision.version}` : "none"}; suppression list
            revision {result.suppression_revision}; evaluated {karachiTime(result.evaluated_at)}.
          </p>
        </div>
      ) : null}
    </section>
  );
}
