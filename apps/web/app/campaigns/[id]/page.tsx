import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../lib/api";
import { type CampaignView, NO_CONTACT, type Preview } from "../../../lib/campaigns";
import { SCENARIOS, SIMULATION_LABEL, type SimulationRun } from "../../../lib/simulations";
import { CandidateActions, DryRun, Lifecycle } from "./actions";

export const dynamic = "force-dynamic";

export default async function CampaignPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const path = `/api/v1/campaigns/${encodeURIComponent(id)}`;
  const [{ body: me }, response] = await Promise.all([apiGet<CurrentUser>("/api/v1/auth/me"), apiGet<CampaignView>(path)]);
  if (response.status === 404 || response.status === 422) notFound();
  const campaign = response.body;
  const preview = (await apiGet<Preview>(`${path}/preview?limit=30`)).body;
  const runs = (await apiGet<{ items: SimulationRun[] }>(`${path}/simulations`)).body.items;
  const canEdit = me.role !== "observer";
  const open = campaign.status === "draft" || campaign.status === "active";
  return (
    <main>
      <p>
        <Link href="/campaigns">All campaigns</Link>
      </p>
      <h1>{campaign.name}</h1>
      <p role="note">
        <strong>{NO_CONTACT}</strong>
      </p>
      <p role="status">
        Status: {campaign.status}
        {campaign.mode === "fixture" ? " (test-only fixture campaign: synthetic data, never active)" : ""}; revision {campaign.revision};
        offer capabilities {campaign.capability_version}
        {campaign.offer_current ? "" : " (offer no longer published: approvals blocked)"}
      </p>
      {campaign.approval_blocked_reason ? <p>Approvals blocked: {campaign.approval_blocked_reason}</p> : null}
      {canEdit ? <Lifecycle campaignId={campaign.id} status={campaign.status} mode={campaign.mode} /> : null}
      <h2>Candidate preview</h2>
      <p>
        {preview.qualifying} qualifying of {preview.total} school accounts (decisions: {campaign.rules.decisions.join(", ")}). Approval
        means a reviewer may prepare a draft later; it is not permission to contact.
      </p>
      <table>
        <caption>Candidates</caption>
        <thead>
          <tr>
            <th scope="col">School</th>
            <th scope="col">Decision and dimensions</th>
            <th scope="col">Why</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {preview.items.map((item) => (
            <tr key={item.account_id}>
              <td>
                <Link href={`/accounts/${item.account_id}`}>{item.name}</Link>
                {item.provenance !== "real" ? ` (${item.provenance})` : ""}
              </td>
              <td>
                {item.decision ?? "not assessed"}
                {item.dimensions ? `; ${Object.entries(item.dimensions).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(", ")}` : ""}
              </td>
              <td>{item.qualifies ? "qualifies" : item.reasons.join(", ")}</td>
              <td>
                {canEdit ? (
                  <CandidateActions campaignId={campaign.id} revision={campaign.revision} item={item} canApprove={open && item.qualifies && !campaign.approval_blocked_reason && campaign.offer_current} />
                ) : (
                  item.stage ?? ""
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Decisions</h2>
      <ul aria-label="Campaign decisions">
        {campaign.members.map((m) => (
          <li key={m.account_id}>
            {m.name}: {m.stage.replaceAll("_", " ")} ({m.reason}){m.stale.length ? `; stale: ${m.stale.join(", ")}` : ""}; {karachiTime(m.decided_at)}
            {m.stage === "approved_for_drafting" ? (
              <>
                {" "}
                <Link href={`/campaigns/${campaign.id}/accounts/${m.account_id}`}>Draft Studio</Link>
              </>
            ) : null}
          </li>
        ))}
      </ul>
      <section aria-labelledby="dry-run">
        <h2 id="dry-run">Dry run</h2>
        <p>
          <strong>{SIMULATION_LABEL}.</strong> A dry run re-checks up to 30 candidates against current approvals, permission and
          policy, and records simulated outcomes only. There is no real transport.
        </p>
        {me.role !== "observer" ? <DryRun campaignId={campaign.id} scenarios={SCENARIOS} /> : null}
        {runs.length > 0 ? (
          <ul aria-label="Dry runs">
            {runs.map((r) => (
              <li key={r.id}>
                <Link href={`/campaigns/${campaign.id}/simulations/${r.id}`}>
                  {r.scenario.replaceAll("_", " ")} — {r.status}
                </Link>{" "}
                ({karachiTime(r.created_at)}; {r.considered} considered)
              </li>
            ))}
          </ul>
        ) : (
          <p>No dry runs yet.</p>
        )}
      </section>
    </main>
  );
}
