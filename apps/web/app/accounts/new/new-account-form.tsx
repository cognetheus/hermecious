"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { errorMessage, postJson } from "../../../lib/mutate";

export default function NewAccountForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const locality = String(form.get("locality") ?? "").trim();
    setPending(true);
    setError(null);
    try {
      const result = await postJson("/api/v1/accounts", {
        canonical_name: String(form.get("canonical_name") ?? ""),
        city: "Lahore",
        ...(locality ? { locality } : {}),
      });
      if (result.ok) {
        router.push(`/accounts/${(result.data as { id: string }).id}`);
        return;
      }
      setError(errorMessage(result.data));
    } finally {
      setPending(false);
    }
  }

  return (
    <main>
      <p>
        <Link href="/accounts">All accounts</Link>
      </p>
      <h1>New account</h1>
      <form onSubmit={onSubmit}>
        <p>
          <label>
            School name <input name="canonical_name" required maxLength={250} />
          </label>
        </p>
        <p>City: Lahore</p>
        <p>
          <label>
            Locality (optional) <input name="locality" maxLength={160} />
          </label>
        </p>
        <button type="submit" disabled={pending}>
          {pending ? "Creating…" : "Create account"}
        </button>
        {error !== null && <p role="alert">{error}</p>}
      </form>
    </main>
  );
}
