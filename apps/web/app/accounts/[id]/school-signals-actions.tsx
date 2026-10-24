"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { errorMessage, postJson } from "../../../lib/mutate";

export default function GenerateBrief({ accountId }: { accountId: string }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function generate() {
    setPending(true);
    setMessage(null);
    try {
      const result = await postJson(`/api/v1/accounts/${accountId}/school-signals/generate`, {});
      const created = (result.data as { created?: boolean }).created;
      setMessage(result.ok ? (created ? "Brief generated" : "No evidence changed: the existing brief is current") : errorMessage(result.data));
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return (
    <p>
      <button type="button" disabled={pending} onClick={generate}>
        Generate school brief
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}
