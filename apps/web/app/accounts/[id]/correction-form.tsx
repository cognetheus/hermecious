"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import type { Fact } from "../../../lib/accounts";
import { errorMessage, postJson } from "../../../lib/mutate";
import FactFields, { factBody } from "./fact-fields";

export default function CorrectionForm({ accountId, fact }: { accountId: string; fact: Fact }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const { body, error } = factBody(form);
    if (!body) {
      setMessage(error ?? "Invalid input");
      return;
    }
    setPending(true);
    setMessage(null);
    try {
      const result = await postJson(`/api/v1/accounts/${accountId}/facts/${fact.id}/corrections`, {
        ...body,
        reason: String(form.get("reason") ?? ""),
      });
      setMessage(result.ok ? "Correction recorded" : errorMessage(result.data));
      if (result.ok) {
        setOpen(false);
        router.refresh();
      }
    } finally {
      setPending(false);
    }
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} aria-expanded={false}>
        Correct this fact
      </button>
    );
  }
  return (
    <form onSubmit={onSubmit} aria-label={`Correct ${fact.claim_type}`}>
      <p>The original assertion and its source are kept; the correction becomes the current fact.</p>
      <p>
        <label htmlFor={`reason-${fact.id}`}>Reason (required)</label>
        <br />
        <textarea id={`reason-${fact.id}`} name="reason" required minLength={3} maxLength={1000} rows={2} cols={60} />
      </p>
      <FactFields idPrefix={`correct-${fact.id}`} sources={fact.source ? [fact.source] : []} claimType={fact.claim_type} fixedClaimType />
      <button type="submit" disabled={pending}>
        {pending ? "Saving…" : "Record correction"}
      </button>{" "}
      <button type="button" onClick={() => setOpen(false)}>
        Cancel
      </button>
      <p role="status" aria-live="polite">
        {message}
      </p>
    </form>
  );
}
