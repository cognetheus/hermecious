"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { PreviewItem } from "../../../lib/campaigns";
import { newKey } from "../../../lib/discovery";
import { errorMessage, postJson } from "../../../lib/mutate";

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

export function CandidateActions({ campaignId, revision, item, canApprove }: { campaignId: string; revision: number; item: PreviewItem; canApprove: boolean }) {
  const { message, pending, run } = useRun();
  const keys = useMemo(
    () => ({ approve: newKey("approve"), exclude: newKey("exclude") }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [item.item_digest],
  );
  return (
    <span>
      {item.stage ? `${item.stage.replaceAll("_", " ")} ` : null}
      {canApprove && item.stage === null ? (
        <button
          type="button"
          disabled={pending}
          onClick={() =>
            run(
              () => postJson(`/api/v1/campaigns/${campaignId}/candidates/${item.account_id}/approve`, { expected_revision: revision, item_digest: item.item_digest, idempotency_key: keys.approve }),
              "Approved for drafting review",
            )
          }
        >
          Approve for drafting
        </button>
      ) : null}{" "}
      {item.stage !== "excluded" ? (
        <button
          type="button"
          disabled={pending}
          onClick={() =>
            run(
              () => postJson(`/api/v1/campaigns/${campaignId}/candidates/${item.account_id}/exclude`, { reason: "Reviewer excluded this school", idempotency_key: keys.exclude }),
              "Excluded",
            )
          }
        >
          Exclude
        </button>
      ) : null}{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </span>
  );
}

export function Lifecycle({ campaignId, status, mode }: { campaignId: string; status: string; mode: string }) {
  const { message, pending, run } = useRun();
  const act = (action: string) =>
    run(async () => {
      const current = await fetch(`/api/v1/campaigns/${campaignId}`, { cache: "no-store" });
      const { revision } = (await current.json()) as { revision: number };
      return postJson(`/api/v1/campaigns/${campaignId}/${action}`, { expected_revision: revision });
    }, `Campaign ${action}d`);
  return (
    <p>
      {mode === "live" && (status === "draft" || status === "paused") ? (
        <button type="button" disabled={pending} onClick={() => act("activate")}>
          Activate internal planning
        </button>
      ) : null}{" "}
      {status === "draft" || status === "active" ? (
        <button type="button" disabled={pending} onClick={() => act("pause")}>
          Pause campaign
        </button>
      ) : null}{" "}
      {status !== "cancelled" ? (
        <button type="button" disabled={pending} onClick={() => act("cancel")}>
          Cancel campaign
        </button>
      ) : null}{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}
