import Link from "next/link";
import { notFound } from "next/navigation";

import { karachiTime } from "../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../lib/api";
import { safeHttpsUrl } from "../../../lib/discovery";
import type { EvalRun } from "../../../lib/evaluation";
import NewEvaluation from "../new-evaluation";
import { FinalizeRun, ItemReview } from "./actions";

export const dynamic = "force-dynamic";

export default async function EvaluationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [{ body: me }, response] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<EvalRun>(`/api/v1/evidence-evals/${encodeURIComponent(id)}`),
  ]);
  if (response.status === 404 || response.status === 422) notFound();
  const run = response.body;
  const canEdit = me.role !== "observer";
  return (
    <main>
      <p>
        <Link href="/quality">All evaluations</Link>
      </p>
      <h1>Evidence evaluation ({run.kind.replace("_", " ")})</h1>
      <p role="status">
        State: <strong>{run.state}</strong>
        {run.result_reason ? ` — ${run.result_reason}` : ""}
      </p>
      <p>
        Corpus {run.corpus_status}: {run.accounts} accounts ({run.real_accounts} real, {run.synthetic_accounts} synthetic,{" "}
        {run.accounts_without_claims} with no displayed facts); seed {run.seed}; fingerprint <code>{run.corpus_fingerprint.slice(0, 16)}</code>
      </p>
      <p>
        {run.denominator !== null
          ? `Supported ${run.numerator}/${run.denominator}; failed claims still displayed: ${run.still_displayed_failures}`
          : `${run.items - run.pending} of ${run.items} claims reviewed`}
        ; created {karachiTime(run.created_at)}
        {run.baseline_run_id ? (
          <>
            {" "}
            (baseline <Link href={`/quality/${run.baseline_run_id}`}>run</Link>)
          </>
        ) : null}
      </p>
      {canEdit && !run.finalized_at ? <FinalizeRun runId={run.id} version={run.version} /> : null}
      {canEdit && run.finalized_at && run.kind === "baseline" ? <NewEvaluation baselineRunId={run.id} /> : null}
      <h2>Displayed factual claims ({run.items})</h2>
      {(run.item_list ?? []).map((item) => {
        const links = item.citations.map((c) => safeHttpsUrl(c.source_url ?? null)).filter((u): u is string => u !== null);
        return (
          <article key={item.id} aria-label={`Claim ${item.display_text.slice(0, 60)}`}>
            <p>
              <strong>{item.item_kind}</strong> on <Link href={`/accounts/${item.account_id}`}>account</Link>
              {item.real_provenance ? "" : " (synthetic)"}: {item.display_text}
            </p>
            <p>
              Evidence at freeze: {item.eligibility_at_freeze}; verdict: {item.verdict ?? "not reviewed"}
              {item.remediation_fact_id ? "; withdrawn as fact (correction recorded)" : ""}
            </p>
            {links.map((link) => (
              <p key={link}>
                Source:{" "}
                <a href={link} rel="noopener noreferrer nofollow" target="_blank">
                  {link}
                </a>
              </p>
            ))}
            {canEdit ? <ItemReview runId={run.id} item={item} finalized={Boolean(run.finalized_at)} /> : null}
          </article>
        );
      })}
    </main>
  );
}
