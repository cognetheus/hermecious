"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useState } from "react";

import { INTENT_LABELS, OWNERSHIP_COMMANDS, OWNERSHIP_REASONS, words } from "../../../lib/inbox";
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

/** P6.3: a human ownership command. The revision makes a stale screen fail loudly instead of overwriting. */
export function OwnershipControls({
  threadId,
  revision,
  assignees,
  isOwner,
}: {
  threadId: string;
  revision: number;
  assignees: { id: string; name: string }[];
  isOwner: boolean;
}) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [command, setCommand] = useState<string>("takeover");
  const commands = OWNERSHIP_COMMANDS.filter((c) => isOwner || (c !== "block" && c !== "reopen"));
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const assignee = String(form.get("assignee") ?? "");
    setPending(true);
    try {
      const result = await postJson(`/api/v1/inbox/whatsapp/threads/${threadId}/ownership`, {
        command,
        expected_revision: revision,
        reason: String(form.get("reason") ?? "manual"),
        note: String(form.get("note") ?? ""),
        idempotency_key: `own-${crypto.randomUUID()}`,
        ...(command === "assign" || command === "open_handoff" ? { assignee_id: assignee || null } : {}),
        urgency: form.get("urgent") ? "high" : "normal",
      });
      setMessage(result.ok ? `Done: ${words(command)} (nothing was sent)` : errorMessage(result.data));
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return (
    <form onSubmit={submit} aria-label="Change ownership">
      <label>
        Action{" "}
        <select name="command" value={command} onChange={(e) => setCommand(e.target.value)}>
          {commands.map((c) => (
            <option key={c} value={c}>
              {words(c)}
            </option>
          ))}
        </select>
      </label>{" "}
      <label>
        Reason{" "}
        <select name="reason" defaultValue="operator_takeover">
          {OWNERSHIP_REASONS.map((r) => (
            <option key={r} value={r}>
              {words(r)}
            </option>
          ))}
        </select>
      </label>{" "}
      {command === "assign" || command === "open_handoff" ? (
        <label>
          Assign to{" "}
          <select name="assignee" defaultValue="" required={command === "assign"}>
            <option value="">(choose)</option>
            {assignees.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}{" "}
      <label>
        Note <input name="note" maxLength={300} size={24} />
      </label>{" "}
      <label>
        <input type="checkbox" name="urgent" /> urgent
      </label>{" "}
      <button type="submit" disabled={pending}>
        Apply
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </form>
  );
}
