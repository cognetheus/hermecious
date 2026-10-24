"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { errorMessage, postJson } from "../../../../../lib/mutate";

export function AutoRefresh({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(timer);
  }, [active, router]);
  return null;
}

export function CancelRun({ campaignId, runId }: { campaignId: string; runId: string }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function cancel() {
    setPending(true);
    try {
      const result = await postJson(`/api/v1/campaigns/${campaignId}/simulations/${runId}/cancel`, {});
      setMessage(result.ok ? "Cancel requested" : errorMessage(result.data));
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return (
    <p>
      <button type="button" disabled={pending} onClick={cancel}>
        Cancel run
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}
