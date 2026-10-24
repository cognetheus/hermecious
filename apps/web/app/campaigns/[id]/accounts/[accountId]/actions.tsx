"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { newKey } from "../../../../../lib/discovery";
import { errorMessage, postJson } from "../../../../../lib/mutate";

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

export function GenerateDraft({ campaignId, accountId }: { campaignId: string; accountId: string }) {
  const { message, pending, run } = useRun();
  const [template, setTemplate] = useState("school_introduction_v1");
  const key = useMemo(() => newKey("draft"), []);
  return (
    <p>
      <label htmlFor="draft-template">Template</label>{" "}
      <select id="draft-template" value={template} onChange={(e) => setTemplate(e.target.value)}>
        <option value="school_introduction_v1">school introduction</option>
        <option value="school_question_v1">school question</option>
      </select>{" "}
      <label htmlFor="draft-locale">Language</label>{" "}
      <select id="draft-locale" defaultValue="en-PK">
        <option value="en-PK">English (Pakistan)</option>
        <option value="ur-PK" disabled>
          Urdu (no reviewed template yet)
        </option>
      </select>{" "}
      <button
        type="button"
        disabled={pending}
        onClick={() => run(() => postJson(`/api/v1/campaigns/${campaignId}/accounts/${accountId}/drafts`, { template_id: template, locale: "en-PK", idempotency_key: key }), "Draft created for review")}
      >
        Generate draft
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}

export function RegenerateDraft({ draftId }: { draftId: string }) {
  const { message, pending, run } = useRun();
  const [reason, setReason] = useState("");
  const key = useMemo(() => newKey("regen"), []);
  return (
    <p>
      <label htmlFor="regen-reason">Reason to regenerate</label>{" "}
      <input id="regen-reason" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={500} />{" "}
      <button type="button" disabled={pending || reason.trim().length < 3} onClick={() => run(() => postJson(`/api/v1/drafts/${draftId}/regenerate`, { reason, idempotency_key: key }), "New revision created")}>
        Regenerate (new revision)
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}

export function EditDraft({ draftId, revision, body }: { draftId: string; revision: number; body: string }) {
  const { message, pending, run } = useRun();
  const [text, setText] = useState(body);
  const [reason, setReason] = useState("");
  return (
    <form aria-label="Edit draft" onSubmit={(e) => e.preventDefault()}>
      <p>
        Edits may drop, reorder or swap sentences from the reviewed template and the cited evidence. New wording is
        refused so every claim stays grounded. Saving creates a new revision; approvals never carry over.
      </p>
      <label htmlFor="edit-text">Edited text</label>
      <br />
      <textarea id="edit-text" value={text} onChange={(e) => setText(e.target.value)} rows={6} cols={80} maxLength={2000} />
      <br />
      <label htmlFor="edit-reason">Reason for edit</label>{" "}
      <input id="edit-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />{" "}
      <button
        type="button"
        disabled={pending || reason.trim().length < 3}
        onClick={() =>
          run(() => postJson(`/api/v1/drafts/${draftId}/revisions`, { edited_text: text, reason, expected_revision: revision, idempotency_key: newKey("edit") }), "New revision saved")
        }
      >
        Save as new revision
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </form>
  );
}

type ContactOption = { id: string; address: string; suppressed: boolean };

export function ReviewDraft({
  draftId,
  digest,
  contacts,
  templates,
  approvalId,
}: {
  draftId: string;
  digest: string;
  contacts: ContactOption[];
  templates: { id: string; category: string; provider_status: string }[];
  approvalId: string | null;
}) {
  const { message, pending, run } = useRun();
  const [contact, setContact] = useState("");
  const [template, setTemplate] = useState("");
  const [reason, setReason] = useState("");
  const ready = reason.trim().length >= 3;
  return (
    <form aria-label="Review content" onSubmit={(e) => e.preventDefault()}>
      <label htmlFor="review-contact">Contact</label>{" "}
      <select id="review-contact" value={contact} onChange={(e) => setContact(e.target.value)}>
        <option value="">(choose a contact)</option>
        {contacts.map((c) => (
          <option key={c.id} value={c.id}>
            {c.address}
            {c.suppressed ? " (suppressed)" : ""}
          </option>
        ))}
      </select>{" "}
      <label htmlFor="review-template">Template</label>{" "}
      <select id="review-template" value={template} onChange={(e) => setTemplate(e.target.value)}>
        <option value="">(choose a template)</option>
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.id} (synthetic fixture: {t.category}, {t.provider_status})
          </option>
        ))}
      </select>{" "}
      <label htmlFor="review-reason">Review reason</label>{" "}
      <input id="review-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />{" "}
      {approvalId ? (
        <button
          type="button"
          disabled={pending || !ready}
          onClick={() => run(() => postJson(`/api/v1/drafts/${draftId}/revoke-approval`, { approval_id: approvalId, reason, idempotency_key: newKey("revoke") }), "Approval revoked")}
        >
          Revoke approval
        </button>
      ) : (
        <>
          <button
            type="button"
            disabled={pending || !ready}
            onClick={() =>
              run(
                () =>
                  postJson(`/api/v1/drafts/${draftId}/approve`, {
                    content_digest: digest,
                    contact_id: contact || null,
                    template_ref: template || null,
                    reason,
                    idempotency_key: newKey("approve"),
                  }),
                "Content approved (simulation only)",
              )
            }
          >
            Approve content only
          </button>{" "}
          <button
            type="button"
            disabled={pending || !ready}
            onClick={() => run(() => postJson(`/api/v1/drafts/${draftId}/reject`, { content_digest: digest, reason, idempotency_key: newKey("reject") }), "Rejected")}
          >
            Reject
          </button>
        </>
      )}{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </form>
  );
}
