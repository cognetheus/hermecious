"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { INTENT_LABELS, words } from "../../../lib/inbox";
import { errorMessage, postJson } from "../../../lib/mutate";

/** Polling is enough for a read-only inbox (no realtime infrastructure). */
export function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => router.refresh(), seconds * 1000);
    return () => clearInterval(timer);
  }, [seconds, router]);
  return null;
}

export function MarkReviewed({ threadId, throughSeq }: { threadId: string; throughSeq: number }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function review() {
    setPending(true);
    try {
      const result = await postJson(`/api/v1/inbox/whatsapp/threads/${threadId}/review`, { through_seq: throughSeq });
      setMessage(result.ok ? "Marked reviewed (local only; nothing was sent)" : errorMessage(result.data));
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return (
    <p>
      <button type="button" disabled={pending} onClick={review}>
        Mark reviewed
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}

/** P6.1: the operator's own judgement of an intent observation. Stored separately; it changes nothing else. */
export function IntentReview({ messageId, observationId }: { messageId: string; observationId: string }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const corrected = String(form.get("label") ?? "");
    setPending(true);
    try {
      const result = await postJson(`/api/v1/inbox/whatsapp/messages/${messageId}/intent-review`, {
        observation_id: observationId,
        decision: corrected ? "corrected" : "confirmed",
        corrected_primary: corrected || null,
        note: String(form.get("note") ?? ""),
      });
      setMessage(result.ok ? "Review recorded" : errorMessage(result.data));
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return (
    <form onSubmit={submit} aria-label="Review intent">
      <label>
        Correct label{" "}
        <select name="label" defaultValue="">
          <option value="">(the label is right)</option>
          {INTENT_LABELS.map((l) => (
            <option key={l} value={l}>
              {words(l)}
            </option>
          ))}
        </select>
      </label>{" "}
      <label>
        Note <input name="note" maxLength={500} size={30} />
      </label>{" "}
      <button type="submit" disabled={pending}>
        Record review
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </form>
  );
}

/** P6.2: ask for a grounded draft (or an abstention) for one inbound message. It is never sent. */
export function SuggestReply({ messageId, label }: { messageId: string; label: string }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function suggest() {
    setPending(true);
    try {
      const result = await postJson(`/api/v1/inbox/whatsapp/messages/${messageId}/reply-proposals`, {});
      setMessage(result.ok ? "Suggestion ready (draft only; nothing was sent)" : errorMessage(result.data));
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return (
    <p>
      <button type="button" disabled={pending} onClick={suggest}>
        {label}
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}

export function RejectProposal({ messageId, proposalId }: { messageId: string; proposalId: string }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      const result = await postJson(`/api/v1/inbox/whatsapp/messages/${messageId}/reply-proposals/${proposalId}/reject`, {
        reason: String(form.get("reason") ?? ""),
      });
      setMessage(result.ok ? "Rejected" : errorMessage(result.data));
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return (
    <form onSubmit={submit} aria-label="Reject suggestion">
      <label>
        Reason <input name="reason" required minLength={3} maxLength={500} size={30} />
      </label>{" "}
      <button type="submit" disabled={pending}>
        Reject suggestion
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </form>
  );
}
