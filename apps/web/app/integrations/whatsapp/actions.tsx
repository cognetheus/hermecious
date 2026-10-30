"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { errorMessage, postJson } from "../../../lib/mutate";
import { type Preview, REAL_SEND_LABEL, type Template, type TestRecipient, type TestSend } from "../../../lib/whatsapp";

const BASE = "/api/v1/integrations/whatsapp";

function useAction() {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function run(path: string, body: unknown, done: string): Promise<unknown> {
    setPending(true);
    try {
      const result = await postJson(`${BASE}${path}`, body);
      setMessage(result.ok ? done : errorMessage(result.data));
      router.refresh();
      return result.ok ? result.data : null;
    } finally {
      setPending(false);
    }
  }
  const status = (
    <span role="status" aria-live="polite">
      {message}
    </span>
  );
  return { run, pending, status };
}

export function SyncTemplates() {
  const { run, pending, status } = useAction();
  return (
    <p>
      <button type="button" disabled={pending} onClick={() => run("/templates/sync", {}, "Catalog synced from Meta")}>
        Sync templates from Meta
      </button>{" "}
      {status}
    </p>
  );
}

export function RecipientForm() {
  const { run, pending, status } = useAction();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await run(
      "/test-recipients",
      { address: form.get("address"), label: form.get("label"), consent_statement: form.get("consent") },
      "Test recipient registered",
    );
  }
  return (
    <form onSubmit={submit} aria-label="Register a test recipient">
      <p>Only a number already listed in the server&apos;s test allowlist can be registered, and never a school contact.</p>
      <label>
        Your own number <input name="address" required minLength={8} maxLength={32} autoComplete="off" />
      </label>{" "}
      <label>
        Label <input name="label" required minLength={2} maxLength={80} />
      </label>
      <br />
      <label>
        Consent statement{" "}
        <input name="consent" required minLength={20} maxLength={500} size={60} placeholder="I own this number and agree to receive test templates." />
      </label>{" "}
      <button type="submit" disabled={pending}>
        Register
      </button>{" "}
      {status}
    </form>
  );
}

export function RevokeRecipient({ id }: { id: string }) {
  const { run, pending, status } = useAction();
  return (
    <>
      {" "}
      <button type="button" disabled={pending} onClick={() => run(`/test-recipients/${id}/revoke`, {}, "Revoked")}>
        Revoke
      </button>{" "}
      {status}
    </>
  );
}

export function PreviewForm({
  templates,
  recipients,
  canConfirm,
}: {
  templates: Template[];
  recipients: TestRecipient[];
  canConfirm: boolean;
}) {
  const { run, pending, status } = useAction();
  const [templateId, setTemplateId] = useState(templates[0]?.id ?? "");
  const [preview, setPreview] = useState<Preview | null>(null);
  const template = templates.find((t) => t.id === templateId);
  if (templates.length === 0 || recipients.length === 0) {
    return <p>A usable (fresh, APPROVED, supported) template and an active test recipient are both required.</p>;
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const parameters = Array.from({ length: template?.body_parameter_count ?? 0 }, (_, i) => String(form.get(`p${i}`) ?? ""));
    const created = (await run(
      "/test-sends",
      { recipient_id: form.get("recipient"), template_id: templateId, parameters, idempotency_key: crypto.randomUUID() },
      "Preview created (nothing sent)",
    )) as Preview | null;
    setPreview(created);
  }
  return (
    <>
      <form onSubmit={submit} aria-label="Preview a test message">
        <label>
          Template{" "}
          <select name="template" value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.language}, {t.category})
              </option>
            ))}
          </select>
        </label>{" "}
        <label>
          Recipient{" "}
          <select name="recipient">
            {recipients.map((r) => (
              <option key={r.id} value={r.id}>
                {r.label} ({r.address})
              </option>
            ))}
          </select>
        </label>
        {Array.from({ length: template?.body_parameter_count ?? 0 }, (_, i) => (
          <label key={`${templateId}-${i}`}>
            {" "}
            Parameter {`{{${i + 1}}}`} <input name={`p${i}`} required maxLength={200} />
          </label>
        ))}{" "}
        <button type="submit" disabled={pending}>
          Preview test
        </button>{" "}
        {status}
      </form>
      {preview && preview.confirmation_nonce ? (
        <ConfirmDialog preview={preview} canConfirm={canConfirm} onClose={() => setPreview(null)} />
      ) : null}
    </>
  );
}

function ConfirmDialog({ preview, canConfirm, onClose }: { preview: Preview; canConfirm: boolean; onClose: () => void }) {
  const { run, pending, status } = useAction();
  const [understood, setUnderstood] = useState(false);
  async function confirm() {
    const sent = await run(
      `/test-sends/${preview.id}/confirm`,
      { preview_digest: preview.preview_digest, confirmation_nonce: preview.confirmation_nonce },
      "Submitted to Meta. Delivery is shown only when a signed webhook arrives.",
    );
    if (sent) onClose();
  }
  return (
    <section role="dialog" aria-modal="true" aria-labelledby="confirm-title" style={{ border: "3px solid currentColor", padding: "0.75rem" }}>
      <h3 id="confirm-title">{REAL_SEND_LABEL}</h3>
      <dl>
        <dt>Template</dt>
        <dd>
          {preview.template?.name} ({preview.template?.language}, {preview.template?.category})
        </dd>
        <dt>Parameters</dt>
        <dd>{preview.parameters && preview.parameters.length > 0 ? preview.parameters.join(" · ") : "none"}</dd>
        <dt>Message</dt>
        <dd>{preview.preview_text ?? "(Meta did not return body text)"}</dd>
        <dt>To</dt>
        <dd>{preview.recipient}</dd>
      </dl>
      {canConfirm ? (
        <>
          <label>
            <input type="checkbox" checked={understood} onChange={(e) => setUnderstood(e.target.checked)} /> I understand
            this sends a real message.
          </label>{" "}
          <button type="button" disabled={pending || !understood} onClick={confirm}>
            Send one real test message
          </button>{" "}
        </>
      ) : (
        <p>Only the owner can confirm this send. The preview expires in 10 minutes.</p>
      )}
      <button type="button" disabled={pending} onClick={onClose}>
        Close
      </button>{" "}
      {status}
    </section>
  );
}

export function PendingSendActions({ send, owner }: { send: TestSend; owner: boolean }) {
  const { run, pending, status } = useAction();
  if (send.state === "awaiting_confirmation") {
    return (
      <p>
        <button type="button" disabled={pending} onClick={() => run(`/test-sends/${send.id}/cancel`, {}, "Cancelled")}>
          Cancel preview
        </button>{" "}
        {status}
      </p>
    );
  }
  if (send.state === "reserved" && owner) {
    return (
      <p>
        <button
          type="button"
          disabled={pending}
          onClick={() => run(`/test-sends/${send.id}/mark-indeterminate`, {}, "Marked indeterminate (never resent)")}
        >
          Mark as indeterminate
        </button>{" "}
        {status}
      </p>
    );
  }
  return null;
}
