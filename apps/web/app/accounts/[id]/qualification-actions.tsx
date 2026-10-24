"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { errorMessage, postJson } from "../../../lib/mutate";
import type { AssessmentView, Decision, Level } from "../../../lib/qualification";

function useRun() {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function run(call: () => Promise<{ ok: boolean; status: number; data: unknown }>, success: (data: unknown) => string) {
    setPending(true);
    setMessage(null);
    try {
      const result = await call();
      setMessage(result.ok ? success(result.data) : `${errorMessage(result.data)}${result.status === 409 ? ". Reload to see the latest assessment." : ""}`);
      if (result.ok) router.refresh();
    } finally {
      setPending(false);
    }
  }
  return { message, pending, run };
}

export function AssessForm({ accountId, offers }: { accountId: string; offers: { id: string; code: string }[] }) {
  const { message, pending, run } = useRun();
  const [offerId, setOfferId] = useState(offers[0]?.id ?? "");
  return (
    <p>
      <label htmlFor="assess-offer">Published offer</label>{" "}
      <select id="assess-offer" value={offerId} onChange={(e) => setOfferId(e.target.value)}>
        <option value="">None selected</option>
        {offers.map((o) => (
          <option key={o.id} value={o.id}>
            {o.code}
          </option>
        ))}
      </select>{" "}
      <button
        type="button"
        disabled={pending}
        onClick={() =>
          run(
            () => postJson(`/api/v1/accounts/${accountId}/assess`, offerId ? { offer_id: offerId } : {}),
            (data) => ((data as { created?: boolean }).created ? "Assessed" : "No inputs changed: the latest assessment stands"),
          )
        }
      >
        Assess account
      </button>{" "}
      <span role="status" aria-live="polite">
        {message}
      </span>
    </p>
  );
}

const LEVELS: Level[] = ["strong", "moderate", "weak", "unknown"];
const DECISIONS: Decision[] = ["contact_now", "investigate", "nurture", "exclude"];

export function OverrideForm({ accountId, assessment }: { accountId: string; assessment: AssessmentView }) {
  const { message, pending, run } = useRun();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const decision = String(form.get("decision") ?? "");
    const dimensions: Record<string, string> = {};
    for (const key of Object.keys(assessment.dimensions)) {
      const value = String(form.get(key) ?? "");
      if (value && value !== assessment.dimensions[key as keyof AssessmentView["dimensions"]].value) dimensions[key] = value;
    }
    await run(
      () =>
        postJson(`/api/v1/accounts/${accountId}/assessments/${assessment.id}/override`, {
          expected_revision: assessment.revision,
          reason: String(form.get("reason") ?? ""),
          ...(decision && decision !== assessment.decision ? { decision } : {}),
          dimensions,
        }),
      () => "Override recorded",
    );
  }
  return (
    <form onSubmit={submit} aria-label="Override assessment">
      <fieldset>
        <legend>Reviewer override (kept alongside the rubric&apos;s explanation)</legend>
        <p>
          <label htmlFor="override-decision">Decision</label>{" "}
          <select id="override-decision" name="decision" defaultValue={assessment.decision}>
            {DECISIONS.map((d) => (
              <option key={d} value={d}>
                {d.replace("_", " ")}
              </option>
            ))}
          </select>
        </p>
        {Object.keys(assessment.dimensions).map((key) => (
          <p key={key}>
            <label htmlFor={`override-${key}`}>{key.replace("_", " ")}</label>{" "}
            <select id={`override-${key}`} name={key} defaultValue={assessment.dimensions[key as keyof AssessmentView["dimensions"]].value}>
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </p>
        ))}
        <p>
          <label htmlFor="override-reason">Reason (required)</label>{" "}
          <input id="override-reason" name="reason" required minLength={3} maxLength={1000} size={50} />
        </p>
        <button type="submit" disabled={pending}>
          Record override (revision {assessment.revision})
        </button>{" "}
        <span role="status" aria-live="polite">
          {message}
        </span>
      </fieldset>
    </form>
  );
}
