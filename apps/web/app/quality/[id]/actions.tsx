"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { EvalItem } from "../../../lib/evaluation";
import { errorMessage, postJson } from "../../../lib/mutate";

const VERDICTS = ["supported", "unsupported", "contradicted", "stale", "unverifiable"] as const;

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

export function ItemReview({ runId, item, finalized }: { runId: string; item: EvalItem; finalized: boolean }) {
  const { message, pending, run } = useRun();
  const [verdict, setVerdict] = useState<string>(item.verdict ?? "supported");
  const [reason, setReason] = useState("Checked the cited source");
  const failed = item.verdict !== null && item.verdict !== "supported";
  return (
    <div role="group" aria-label="Review claim">
      {!finalized ? (
        <p>
          <label htmlFor={`verdict-${item.id}`}>Verdict</label>{" "}
          <select id={`verdict-${item.id}`} value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            {VERDICTS.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>{" "}
          <label htmlFor={`reason-${item.id}`}>Reason</label>{" "}
          <input id={`reason-${item.id}`} value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={1000} />{" "}
          <button
            type="button"
            disabled={pending}
            onClick={() =>
              run(() => postJson(`/api/v1/evidence-evals/${runId}/items/${item.id}/verdict`, { verdict, reason, expected_version: item.version }), "Saved")
            }
          >
            Save verdict
          </button>
        </p>
      ) : null}
      {failed && item.item_kind === "fact" && !item.remediation_fact_id ? (
        <button
          type="button"
          disabled={pending}
          onClick={() => run(() => postJson(`/api/v1/evidence-evals/${runId}/items/${item.id}/remediate`, { reason }), "Withdrawn as fact")}
        >
          Withdraw as fact (record correction)
        </button>
      ) : null}{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </div>
  );
}

export function FinalizeRun({ runId, version }: { runId: string; version: number }) {
  const { message, pending, run } = useRun();
  return (
    <p>
      <button type="button" disabled={pending} onClick={() => run(() => postJson(`/api/v1/evidence-evals/${runId}/finalize`, { expected_version: version }), "Finalized")}>
        Finalize evaluation
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}
