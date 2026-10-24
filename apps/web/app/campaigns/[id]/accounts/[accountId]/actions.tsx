"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { newKey } from "../../../../../lib/discovery";
import { errorMessage, postJson } from "../../../../../lib/mutate";

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

export function GenerateDraft({ campaignId, accountId }: { campaignId: string; accountId: string }) {
  const { message, pending, run } = useRun();
  const [template, setTemplate] = useState("school_introduction_v1");
  const key = useMemo(() => newKey("draft"), []);
  return (
    <p>
      <label htmlFor="draft-template">Template</label>{" "}
      <select id="draft-template" value={template} onChange={(e) => setTemplate(e.target.value)}>
        <option value="school_introduction_v1">school introduction</option>
        <option value="school_question_v1">school question</option>
      </select>{" "}
      <label htmlFor="draft-locale">Language</label>{" "}
      <select id="draft-locale" defaultValue="en-PK">
        <option value="en-PK">English (Pakistan)</option>
        <option value="ur-PK" disabled>
          Urdu (no reviewed template yet)
        </option>
      </select>{" "}
      <button
        type="button"
        disabled={pending}
        onClick={() => run(() => postJson(`/api/v1/campaigns/${campaignId}/accounts/${accountId}/drafts`, { template_id: template, locale: "en-PK", idempotency_key: key }), "Draft created for review")}
      >
        Generate draft
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}

export function RegenerateDraft({ draftId }: { draftId: string }) {
  const { message, pending, run } = useRun();
  const [reason, setReason] = useState("");
  const key = useMemo(() => newKey("regen"), []);
  return (
    <p>
      <label htmlFor="regen-reason">Reason to regenerate</label>{" "}
      <input id="regen-reason" value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={500} />{" "}
      <button type="button" disabled={pending || reason.trim().length < 3} onClick={() => run(() => postJson(`/api/v1/drafts/${draftId}/regenerate`, { reason, idempotency_key: key }), "New revision created")}>
        Regenerate (new revision)
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}
