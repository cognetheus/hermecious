import Link from "next/link";

import { karachiTime } from "../../lib/accounts";
import { apiGet, type CurrentUser } from "../../lib/api";
import { type CampaignSummary, NO_CONTACT } from "../../lib/campaigns";
import NewCampaign from "./new-campaign";

export const dynamic = "force-dynamic";

type OfferSummary = { id: string; code: string; status: string };

export default async function CampaignsPage() {
  const [{ body: me }, campaigns, offers] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<{ items: CampaignSummary[] }>("/api/v1/campaigns"),
    apiGet<{ offers: OfferSummary[] }>("/api/v1/offers"),
  ]);
  const published = offers.status === 200 ? offers.body.offers.filter((o) => o.status === "published") : [];
  return (
    <main>
      <p>
        <Link href="/">Home</Link>
      </p>
      <h1>Campaigns</h1>
      <p role="note">
        <strong>{NO_CONTACT}</strong> Campaigns plan which researched schools may get a draft later. Nothing here sends,
        schedules or records permission to contact anyone.
      </p>
      {me.role !== "observer" ? <NewCampaign offers={published} /> : null}
      {campaigns.body.items.length === 0 ? (
        <p>No campaigns yet.</p>
      ) : (
        <ul aria-label="Campaigns">
          {campaigns.body.items.map((c) => (
            <li key={c.id}>
              <Link href={`/campaigns/${c.id}`}>{c.name}</Link> — {c.status}
              {c.mode === "fixture" ? " (test-only fixture campaign)" : ""}; created {karachiTime(c.created_at)}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
