"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { newKey } from "../../lib/discovery";
import { errorMessage, postJson } from "../../lib/mutate";

export default function NewEvaluation({ baselineRunId }: { baselineRunId?: string }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const key = useMemo(() => newKey("eval"), []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      const result = await postJson(
        "/api/v1/evidence-evals",
        baselineRunId
          ? { kind: "post_remediation", baseline_run_id: baselineRunId, seed: "post", idempotency_key: key }
          : { seed: String(form.get("seed") ?? ""), idempotency_key: key, allow_synthetic: form.get("allow_synthetic") === "on" },
      );
      if (result.ok) {
        router.push(`/quality/${(result.data as { id: string }).id}`);
        return;
      }
      setMessage(errorMessage(result.data));
    } finally {
      setPending(false);
    }
  }
  return (
    <form onSubmit={submit} aria-label={baselineRunId ? "Start post-remediation evaluation" : "Start evaluation"}>
      {baselineRunId ? null : (
        <p>
          <label htmlFor="eval-seed">Selection seed</label>{" "}
          <input id="eval-seed" name="seed" required pattern="[A-Za-z0-9._-]{1,64}" defaultValue="baseline-1" />{" "}
          <input id="eval-synthetic" name="allow_synthetic" type="checkbox" />{" "}
          <label htmlFor="eval-synthetic">Include synthetic accounts (test only; never opens the gate)</label>
        </p>
      )}
      <button type="submit" disabled={pending}>
        {baselineRunId ? "Start post-remediation evaluation" : "Start evaluation"}
      </button>{" "}
      {message ? <span role="alert">{message}</span> : null}
    </form>
  );
}
