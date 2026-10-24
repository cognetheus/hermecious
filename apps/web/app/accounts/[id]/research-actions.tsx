"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { newKey } from "../../../lib/discovery";
import { errorMessage, postJson } from "../../../lib/mutate";
import type { ResearchClaim, ResearchSource } from "../../../lib/research";

export function ResearchRefresher() {
  const router = useRouter();
  useEffect(() => {
    const timer = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(timer);
  }, [router]);
  return null;
}

function useRun() {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function run(call: () => Promise<{ ok: boolean; status: number; data: unknown }>, success: string) {
    setPending(true);
    setMessage(null);
    try {
      const result = await call();
      setMessage(result.ok ? success : `${errorMessage(result.data)}${result.status === 409 ? ". Reload to see the latest state." : ""}`);
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return { message, pending, run };
}

export function StartResearch({ accountId, sources }: { accountId: string; sources: ResearchSource[] }) {
  const { message, pending, run } = useRun();
  const [selected, setSelected] = useState<string[]>([]);
  const key = useMemo(() => newKey("research"), []);
  const eligible = sources.filter((s) => s.eligible);
  return (
    <form
      aria-label="Start research"
      onSubmit={(event) => {
        event.preventDefault();
        run(
          () => postJson(`/api/v1/accounts/${accountId}/research-runs`, { source_record_ids: selected, idempotency_key: key }),
          "Research queued",
        );
      }}
    >
      <fieldset>
        <legend>Sources to research (associated with this account)</legend>
        {sources.map((s) => (
          <p key={s.id}>
            <input
              type="checkbox"
              id={`research-source-${s.id}`}
              disabled={!s.eligible}
              checked={selected.includes(s.id)}
              onChange={(e) => setSelected((prev) => (e.target.checked ? [...prev, s.id].slice(0, 5) : prev.filter((x) => x !== s.id)))}
            />{" "}
            <label htmlFor={`research-source-${s.id}`}>
              {s.provider} ({s.storage_class}){s.eligible ? "" : `: not available (${s.ineligible_reason})`}
            </label>
          </p>
        ))}
      </fieldset>
      <button type="submit" disabled={pending || selected.length === 0 || eligible.length === 0}>
        Run research
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </form>
  );
}

export function CancelResearch({ runId }: { runId: string }) {
  const { message, pending, run } = useRun();
  return (
    <p>
      <button type="button" disabled={pending} onClick={() => run(() => postJson(`/api/v1/research-runs/${runId}/cancel`, {}), "Cancellation requested")}>
        Cancel research
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}

export function ClaimReview({ claim }: { claim: ResearchClaim }) {
  const { message, pending, run } = useRun();
  const [reason, setReason] = useState("Checked the cited text on the source");
  const keys = useMemo(
    () => ({ accept: newKey("accept"), reject: newKey("reject") }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [claim.version],
  );
  const decide = (action: "accept" | "reject") =>
    run(
      () =>
        postJson(`/api/v1/research-claims/${claim.id}/review`, {
          action,
          expected_version: claim.version,
          reason,
          idempotency_key: keys[action],
        }),
      action === "accept" ? "Accepted as a source-supported fact" : "Rejected",
    );
  return (
    <div role="group" aria-label={`Review ${claim.claim_type}`}>
      <label>
        Review reason <input value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={1000} size={50} />
      </label>{" "}
      <button type="button" disabled={pending} onClick={() => decide("accept")}>
        Accept claim
      </button>{" "}
      <button type="button" disabled={pending} onClick={() => decide("reject")}>
        Reject claim
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </div>
  );
}
