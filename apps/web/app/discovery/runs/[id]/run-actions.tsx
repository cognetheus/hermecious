"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { type Match, newKey, type RunCandidate } from "../../../../lib/discovery";
import { errorMessage, postJson } from "../../../../lib/mutate";

/** Polls durable run state while it is queued or running (no websockets). */
export function RunRefresher() {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(timer);
  }, [router]);
  return null;
}

function useAction() {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function run(call: () => Promise<{ ok: boolean; status: number; data: unknown }>, success: string) {
    setPending(true);
    setMessage(null);
    try {
      const result = await call();
      if (result.ok) {
        setMessage(success);
        router.refresh();
      } else {
        setMessage(result.status === 409 ? `${errorMessage(result.data)}. Reload to see the latest state.` : errorMessage(result.data));
      }
    } finally {
      setPending(false);
    }
  }
  return { message, pending, run };
}

export function CancelRun({ runId }: { runId: string }) {
  const { message, pending, run } = useAction();
  return (
    <p>
      <button type="button" disabled={pending} onClick={() => run(() => postJson(`/api/v1/discovery/runs/${runId}/cancel`, {}), "Cancellation requested")}>
        Cancel run
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}

export function ReviewActions({ runId, item }: { runId: string; item: RunCandidate }) {
  const { message, pending, run } = useAction();
  const [reason, setReason] = useState("Reviewed the listing and its source record");
  // A stable key per rendered version: retrying the same click replays, a fresh load gets a new key.
  const keys = useMemo(
    () => ({ accept: newKey("accept"), attach: newKey("attach"), reject: newKey("reject"), defer: newKey("defer") }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [item.version],
  );
  const open = item.review_status === "pending" || item.review_status === "deferred";
  if (!open) {
    return null;
  }
  const decide = (action: string, key: string, extra: Record<string, unknown> = {}) =>
    run(
      () =>
        postJson(`/api/v1/discovery/runs/${runId}/candidates/${item.candidate_id}/decision`, {
          action,
          expected_version: item.version,
          idempotency_key: key,
          reason,
          ...extra,
        }),
      action === "accept_new" || action === "attach_existing" ? "Admitted as an account (research pending)" : "Saved",
    );
  return (
    <div role="group" aria-label={`Review ${item.display_name}`}>
      <p>
        <label>
          Review reason <input value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={1000} size={50} />
        </label>
      </p>
      <p>
        <button type="button" disabled={pending || item.expired} onClick={() => decide("accept_new", keys.accept)}>
          Accept as new campus
        </button>{" "}
        {item.linked_account_id ? (
          <button
            type="button"
            disabled={pending || item.expired}
            onClick={() => decide("attach_existing", keys.attach, { existing_account_id: item.linked_account_id })}
          >
            Attach to confirmed account
          </button>
        ) : null}{" "}
        <button type="button" disabled={pending} onClick={() => decide("reject", keys.reject)}>
          Reject
        </button>{" "}
        {item.review_status === "pending" ? (
          <button type="button" disabled={pending} onClick={() => decide("defer", keys.defer)}>
            Defer
          </button>
        ) : null}
      </p>
      {item.expired ? <p>Source rights have expired: a new permitted observation is needed before admission.</p> : null}
      <p role="status" aria-live="polite">
        {message}
      </p>
    </div>
  );
}

export function MatchActions({ match }: { match: Match }) {
  const { message, pending, run } = useAction();
  const open = ["pending", "deferred", "undone"].includes(match.status);
  if (!open) {
    return null;
  }
  const decide = (action: "confirm_same_campus" | "mark_distinct") =>
    run(
      () =>
        postJson(`/api/v1/identity/suggestions/${match.suggestion_id}/decisions`, {
          command_id: crypto.randomUUID(),
          action,
          expected_version: match.version,
          reason: action === "mark_distinct" ? "Reviewer: different campuses" : "Reviewer: same campus",
        }),
      "Saved",
    );
  return (
    <span>
      {" "}
      <button type="button" disabled={pending} onClick={() => decide("confirm_same_campus")}>
        Same campus
      </button>{" "}
      <button type="button" disabled={pending} onClick={() => decide("mark_distinct")}>
        Different campus
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </span>
  );
}
