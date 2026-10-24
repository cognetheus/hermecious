"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { errorMessage, postJson } from "../../../lib/mutate";

type Props = {
  offerId: string;
  role: "owner" | "operator" | "observer";
  status: "draft" | "published" | "archived";
  version: number;
  draftRevision: number | null;
  initialContent: string;
};

export default function OfferActions({ offerId, role, status, version, draftRevision, initialContent }: Props) {
  const router = useRouter();
  const [content, setContent] = useState(initialContent);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (role === "observer" || status === "archived") {
    return null;
  }

  async function run(path: string, body: unknown, success: string) {
    setPending(true);
    setMessage(null);
    try {
      const result = await postJson(`/api/v1/offers/${offerId}${path}`, body);
      setMessage(result.ok ? success : errorMessage(result.data));
      if (result.ok) {
        router.refresh();
      }
    } finally {
      setPending(false);
    }
  }

  async function submitRevision() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(content);
    } catch {
      setMessage("Revision content is not valid JSON");
      return;
    }
    await run("/revisions", { expected_version: version, content: parsed }, "Draft revision created");
  }

  return (
    <section>
      <h2>Actions</h2>
      {role === "owner" && draftRevision !== null ? (
        <button
          type="button"
          disabled={pending}
          onClick={() => run("/publish", { revision: draftRevision, expected_version: version }, "Published")}
        >
          Publish draft revision {draftRevision}
        </button>
      ) : null}
      {role === "owner" ? (
        <button
          type="button"
          disabled={pending}
          onClick={() => run("/archive", { expected_version: version }, "Archived")}
        >
          Archive offer
        </button>
      ) : null}
      <h3>New draft revision</h3>
      <p>Edits always create a new revision; published revisions never change.</p>
      <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={18} cols={100} spellCheck={false} />
      <div>
        <button type="button" disabled={pending} onClick={submitRevision}>
          Save as new draft revision
        </button>
      </div>
      {message !== null && <p role="status">{message}</p>}
    </section>
  );
}
