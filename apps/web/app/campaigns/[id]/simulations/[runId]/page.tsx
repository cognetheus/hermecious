import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../../../lib/api";
import { share, SIMULATION_LABEL, type SimulationRun } from "../../../../../lib/simulations";
import { AutoRefresh, CancelRun } from "./actions";

export const dynamic = "force-dynamic";

export default async function DryRunReport({ params }: { params: Promise<{ id: string; runId: string }> }) {
  const { id, runId } = await params;
  const [{ body: me }, response] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<SimulationRun>(`/api/v1/campaigns/${encodeURIComponent(id)}/simulations/${encodeURIComponent(runId)}`),
  ]);
  if (response.status === 404 || response.status === 422) notFound();
  const run = response.body;
  const active = run.status === "pending" || run.status === "running";
  const report = run.report;
  return (
    <main>
      <AutoRefresh active={active} />
      <p>
        <Link href={`/campaigns/${id}`}>Back to campaign</Link>
      </p>
      <h1>Dry run report</h1>
      <p role="alert" style={{ fontSize: "1.4rem", fontWeight: 700, border: "3px solid currentColor", padding: "0.5rem" }}>
        {SIMULATION_LABEL}
      </p>
      <p role="status">
        Status: {run.status}
        {run.cancel_requested && active ? " (cancel requested)" : ""}
      </p>
      <p>
        Scenario {run.scenario.replaceAll("_", " ")} · {run.mode === "fixture" ? "synthetic fixture campaign" : "readiness only (no simulated delivery)"} · evaluated at{" "}
        {karachiTime(run.evaluated_at)} · {run.policy_version} · {run.simulator_version}
        {run.report_digest ? ` · report digest ${run.report_digest.slice(0, 12)}` : ""}
      </p>
      {active && me.role !== "observer" ? <CancelRun campaignId={id} runId={runId} /> : null}
      {report ? (
        <section aria-labelledby="summary">
          <h2 id="summary">Summary ({report.considered} considered)</h2>
          <ul aria-label="Decisions">
            <li>Accepted for simulation: {share(report.buckets.accepted)}</li>
            <li>Denied: {share(report.buckets.denied)}</li>
            <li>Deferred: {share(report.buckets.deferred)}</li>
            <li>Invalid: {share(report.buckets.invalid)}</li>
          </ul>
          <ul aria-label="Simulated lifecycle">
            <li>Simulated delivered: {share(report.lifecycle.sim_delivered)}</li>
            <li>Simulated failed: {share(report.lifecycle.sim_failed)}</li>
          </ul>
          <p>{report.reconciled ? "Counts reconcile with the records considered." : "Counts do not reconcile."} These are simulated outcomes, not WhatsApp delivery figures.</p>
          <h3>Missing before real outreach</h3>
          <ul aria-label="Missing prerequisites">
            {Object.entries(report.missing_prerequisites).map(([name, count]) => (
              <li key={name}>
                {name}: {count} of {report.considered}
              </li>
            ))}
            {report.standing_blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
          <p>
            <a href={`/api/v1/campaigns/${id}/simulations/${runId}/export.csv`}>Download redacted CSV</a>
          </p>
        </section>
      ) : null}
      <table>
        <caption>Per-account decisions</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Account</th>
            <th scope="col">Decision</th>
            <th scope="col">Why</th>
            <th scope="col">Simulated lifecycle</th>
          </tr>
        </thead>
        <tbody>
          {(run.items ?? []).map((i) => (
            <tr key={i.account_id}>
              <td>{i.seq}</td>
              <td>{i.account}</td>
              <td>{i.bucket}</td>
              <td>
                {i.reasons.join(", ") || "all checks passed"}
                {i.next_window_at ? ` (earliest window ${karachiTime(i.next_window_at)})` : ""}
              </td>
              <td>
                {i.lifecycle.replaceAll("_", " ")}
                {i.sim_receipt_id ? ` (${i.sim_receipt_id})` : ""}
                {i.attempts > 1 ? `, ${i.attempts} attempts` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
