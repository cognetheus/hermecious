import Link from "next/link";

import { karachiTime } from "../../lib/accounts";
import { apiGet, type CurrentUser } from "../../lib/api";
import type { EvalRun, Gate } from "../../lib/evaluation";
import NewEvaluation from "./new-evaluation";

export const dynamic = "force-dynamic";

export default async function QualityPage() {
  const [{ body: me }, runs, gate] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<{ items: EvalRun[] }>("/api/v1/evidence-evals"),
    apiGet<Gate>("/api/v1/evidence-evals/gate"),
  ]);
  return (
    <main>
      <p>
        <Link href="/">Home</Link>
      </p>
      <h1>Evidence quality</h1>
      <p role="status">
        Enrollment quality gate: <strong>{gate.body.enrollment_allowed ? "OPEN" : "CLOSED"}</strong> ({gate.body.status}:{" "}
        {gate.body.reason})
      </p>
      <p>
        An evaluation freezes up to 30 distinct accounts and every claim they display as fact. A person judges each
        claim against its cited source. The gate opens only when 30 real accounts reach at least 90% supported and no
        failed claim is still displayed. Synthetic or smaller samples never open it.
      </p>
      {me.role !== "observer" ? <NewEvaluation /> : null}
      {runs.body.items.length === 0 ? (
        <p>No evaluations yet.</p>
      ) : (
        <table>
          <caption>Evaluations, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Created (Asia/Karachi)</th>
              <th scope="col">Kind</th>
              <th scope="col">State</th>
              <th scope="col">Supported</th>
              <th scope="col">Corpus</th>
            </tr>
          </thead>
          <tbody>
            {runs.body.items.map((run) => (
              <tr key={run.id}>
                <td>
                  <Link href={`/quality/${run.id}`}>{karachiTime(run.created_at)}</Link>
                </td>
                <td>{run.kind.replace("_", " ")}</td>
                <td>{run.state}</td>
                <td>{run.denominator !== null ? `${run.numerator}/${run.denominator}` : `${run.items - run.pending}/${run.items} reviewed`}</td>
                <td>
                  {run.corpus_status} ({run.real_accounts} real, {run.synthetic_accounts} synthetic)
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
