"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { newKey, type SourceOption } from "../../../lib/discovery";
import { errorMessage, postJson } from "../../../lib/mutate";

type Ceilings = { max_candidates: number; max_search_pages: number; max_fetches: number; max_seconds: number };

export default function NewRunForm({ sources, ceilings, city }: { sources: SourceOption[]; ceilings: Ceilings; city: string }) {
  const router = useRouter();
  const [provider, setProvider] = useState(sources[0].provider);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  // One key per form instance: a double submit replays the same run instead of starting two.
  const idempotencyKey = useMemo(() => newKey("run"), []);
  const source = sources.find((s) => s.provider === provider) ?? sources[0];
  const maxCandidates = Math.min(ceilings.max_candidates, source.max_candidates);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const number = (name: string) => Number(form.get(name));
    setPending(true);
    setError(null);
    try {
      const result = await postJson("/api/v1/discovery/runs", {
        provider,
        idempotency_key: idempotencyKey,
        budget: {
          max_candidates: number("max_candidates"),
          max_search_pages: number("max_search_pages"),
          max_fetches: number("max_fetches"),
          max_seconds: number("max_seconds"),
        },
      });
      if (result.ok) {
        router.push(`/discovery/runs/${(result.data as { id: string }).id}`);
        return;
      }
      setError(errorMessage(result.data));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} aria-label="New discovery run">
      <p>
        <label htmlFor="run-provider">Source</label>{" "}
        <select id="run-provider" name="provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {sources.map((s) => (
              <option key={s.provider} value={s.provider}>
                {s.label}
              </option>
          ))}
        </select>
      </p>
      <section aria-label="Source rights">
        <h2>Area and rights</h2>
        <p>
          City: {city}. Area: {source.area_label} (set by the server; there is no free-form area or map box).
        </p>
        <p>
          Vertical: schools. Storage: {source.storage}, kept {source.retention_days} days. Rights policy{" "}
          {source.rights_policy_version}. At most {source.request_quota} source requests.
        </p>
        {source.attribution ? <p>Attribution: {source.attribution}</p> : null}
        {source.synthetic ? <p>Synthetic fixture: fictional records, not real Lahore schools.</p> : null}
      </section>
      <fieldset>
        <legend>Budget (can only be lowered)</legend>
        <p>
          <label htmlFor="run-max-candidates">Maximum listings</label>{" "}
          <input id="run-max-candidates" name="max_candidates" type="number" min={1} max={maxCandidates} defaultValue={maxCandidates} required />{" "}
          <label htmlFor="run-max-pages">Search pages</label>{" "}
          <input id="run-max-pages" name="max_search_pages" type="number" min={1} max={ceilings.max_search_pages} defaultValue={ceilings.max_search_pages} required />
        </p>
        <p>
          <label htmlFor="run-max-fetches">Item fetches</label>{" "}
          <input id="run-max-fetches" name="max_fetches" type="number" min={0} max={ceilings.max_fetches} defaultValue={ceilings.max_fetches} required />{" "}
          <label htmlFor="run-max-seconds">Seconds</label>{" "}
          <input id="run-max-seconds" name="max_seconds" type="number" min={5} max={ceilings.max_seconds} defaultValue={ceilings.max_seconds} required />
        </p>
      </fieldset>
      <button type="submit" disabled={pending}>
        {pending ? "Starting…" : "Start run"}
      </button>
      {error !== null && <p role="alert">{error}</p>}
    </form>
  );
}
