"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

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
