"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import type { Source } from "../../../lib/accounts";
import { errorMessage, postJson } from "../../../lib/mutate";
import FactFields, { factBody } from "./fact-fields";

export default function EvidenceForm({ accountId, sources }: { accountId: string; sources: Source[] }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const { body, error } = factBody(new FormData(formElement));
    if (!body) {
      setMessage(error ?? "Invalid input");
      return;
    }
    setPending(true);
    setMessage(null);
    try {
      const result = await postJson(`/api/v1/accounts/${accountId}/facts`, body);
      setMessage(result.ok ? "Fact recorded" : errorMessage(result.data));
      if (result.ok) {
        formElement.reset();
        router.refresh();
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="add-evidence">
      <h2 id="add-evidence">Add evidence or a hypothesis</h2>
      <form onSubmit={onSubmit}>
        <FactFields idPrefix="add" sources={sources} />
        <button type="submit" disabled={pending}>
          {pending ? "Saving…" : "Record fact"}
        </button>
        <p role="status" aria-live="polite">
          {message}
        </p>
      </form>
    </section>
  );
}
