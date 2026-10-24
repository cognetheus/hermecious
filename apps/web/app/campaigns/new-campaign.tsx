"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { errorMessage, postJson } from "../../lib/mutate";

export default function NewCampaign({ offers }: { offers: { id: string; code: string }[] }) {
  const router = useRouter();
  const [message, setMessage] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const decisions = ["contact_now", "investigate"].filter((d) => form.get(`decision-${d}`) === "on");
    setPending(true);
    try {
      const result = await postJson("/api/v1/campaigns", {
        name: String(form.get("name") ?? ""),
        offer_id: String(form.get("offer_id") ?? ""),
        mode: String(form.get("mode") ?? "live"),
        rules: { decisions: decisions.length ? decisions : ["contact_now"] },
        budgets: { approvals_per_day: Number(form.get("approvals_per_day") ?? 10) },
      });
      if (result.ok) {
        router.push(`/campaigns/${(result.data as { id: string }).id}`);
        return;
      }
      setMessage(errorMessage(result.data));
    } finally {
      setPending(false);
    }
  }
  if (offers.length === 0) return <p>Publish an offer first: campaigns attach to a published offer revision.</p>;
  return (
    <form onSubmit={submit} aria-label="New campaign">
      <p>
        <label htmlFor="campaign-name">Campaign name</label>{" "}
        <input id="campaign-name" name="name" required minLength={3} maxLength={120} />
      </p>
      <p>
        <label htmlFor="campaign-offer">Published offer</label>{" "}
        <select id="campaign-offer" name="offer_id">
          {offers.map((o) => (
            <option key={o.id} value={o.id}>
              {o.code}
            </option>
          ))}
        </select>{" "}
        <label htmlFor="campaign-mode">Mode</label>{" "}
        <select id="campaign-mode" name="mode" defaultValue="live">
          <option value="live">live (needs a passed evidence evaluation)</option>
          <option value="fixture">fixture (synthetic test data only)</option>
        </select>
      </p>
      <fieldset>
        <legend>Target decisions (Lahore schools only)</legend>
        <input id="decision-contact_now" name="decision-contact_now" type="checkbox" defaultChecked />{" "}
        <label htmlFor="decision-contact_now">contact now (research priority)</label>{" "}
        <input id="decision-investigate" name="decision-investigate" type="checkbox" />{" "}
        <label htmlFor="decision-investigate">investigate</label>
      </fieldset>
      <p>
        <label htmlFor="campaign-approvals">Approvals per day (local planning budget, max 10)</label>{" "}
        <input id="campaign-approvals" name="approvals_per_day" type="number" min={0} max={10} defaultValue={10} />
      </p>
      <button type="submit" disabled={pending}>
        Create campaign
      </button>{" "}
      {message ? <span role="alert">{message}</span> : null}
    </form>
  );
}
