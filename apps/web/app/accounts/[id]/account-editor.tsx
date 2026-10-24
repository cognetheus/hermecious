"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { type Account, STATUSES } from "../../../lib/accounts";
import { errorMessage, postJson } from "../../../lib/mutate";

export default function AccountEditor({ account, role }: { account: Account; role: "owner" | "operator" | "observer" }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const archived = account.status === "excluded";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const changes: Record<string, unknown> = { expected_version: account.version };
    const name = String(form.get("canonical_name") ?? "").trim();
    const locality = String(form.get("locality") ?? "").trim();
    const status = String(form.get("status") ?? "");
    if (name !== account.canonical_name) changes.canonical_name = name;
    if (locality !== (account.locality ?? "")) changes.locality = locality || null;
    if (status !== account.status) changes.status = status;
    if (Object.keys(changes).length === 1) {
      setMessage("Nothing changed");
      return;
    }
    await run(() => postJson(`/api/v1/accounts/${account.id}`, changes, "PATCH"), "Saved");
  }

  async function run(call: () => Promise<{ ok: boolean; data: unknown }>, success: string) {
    setPending(true);
    setMessage(null);
    try {
      const result = await call();
      setMessage(result.ok ? success : errorMessage(result.data));
      if (result.ok) {
        router.refresh();
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      {!archived && role !== "observer" ? (
        <form onSubmit={save} aria-label="Edit account">
          <p>
            <label>
              Name <input name="canonical_name" defaultValue={account.canonical_name} required maxLength={250} size={40} />
            </label>
          </p>
          <p>
            <label>
              Locality <input name="locality" defaultValue={account.locality ?? ""} maxLength={160} />
            </label>{" "}
            <label>
              Status{" "}
              <select name="status" defaultValue={account.status}>
                {STATUSES.filter((s) => s !== "excluded").map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          </p>
          <button type="submit" disabled={pending}>
            {pending ? "Saving…" : `Save (version ${account.version})`}
          </button>
        </form>
      ) : null}
      {role === "owner" && !archived ? (
        <button
          type="button"
          disabled={pending}
          onClick={() =>
            run(() => postJson(`/api/v1/accounts/${account.id}/archive`, { expected_version: account.version }), "Archived")
          }
        >
          Archive (exclude) account
        </button>
      ) : null}
      <p role="status" aria-live="polite">
        {message}
      </p>
    </div>
  );
}
