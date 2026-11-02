import Link from "next/link";

import { karachiTime } from "../../../lib/accounts";
import { apiGet, type CurrentUser } from "../../../lib/api";
import { type Readiness, STATUS_LABEL } from "../../../lib/release";
import { AttestForm, AuthorizeForm, AuthorizationActions, Evaluate } from "./actions";

export const dynamic = "force-dynamic";

// Go/no-go review for WhatsApp production (P5.5). Nothing on this page sends a message; there is no send, bulk or
// campaign control. Live sending also needs a separate deploy-time change that this page cannot make.
export default async function ReleaseReadiness() {
  const [{ body: me }, { status, body }] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<Readiness>("/api/v1/release/whatsapp/readiness"),
  ]);
  const owner = me.role === "owner";
  if (status === 403) {
    return (
      <main>
        <p>
          <Link href="/">Home</Link>
        </p>
        <p role="alert">Production readiness is available to owners and operators only.</p>
      </main>
    );
  }
  const a = body.assessment;
  const ready = a !== null && a.fresh && a.status === "ready_for_operator_review";
  const live = body.authorizations.filter((x) => x.status !== "revoked" && !x.expired);
  return (
    <main>
      <p>
        <Link href="/">Home</Link>
      </p>
      <h1>WhatsApp Production Readiness</h1>
      <p role="note" style={{ fontSize: "1.3rem", fontWeight: 700, border: "3px solid currentColor", padding: "0.5rem" }}>
        {body.banner}
      </p>
      <p>
        Deploy-time live gate: <strong>{body.live_gate === "open" ? "open" : `closed (${body.live_gate.replaceAll("_", " ")})`}</strong>. A
        ready report, a Meta-approved template or an approved draft is never permission to contact a school.
      </p>
      <section aria-labelledby="assessment">
        <h2 id="assessment">Latest assessment</h2>
        {owner ? <Evaluate /> : null}
        {a === null ? (
          <p>No assessment yet.</p>
        ) : (
          <>
            <p role="status">
              {STATUS_LABEL[a.status]} · checked {karachiTime(a.checked_at)} · {a.fresh ? `valid until ${karachiTime(a.expires_at)}` : "expired"} · build{" "}
              {a.build_sha ?? "unknown"} · digest {a.digest.slice(0, 12)}
            </p>
            <table aria-label="Prerequisites">
              <thead>
                <tr>
                  <th>Check</th>
                  <th>Status</th>
                  <th>Evidence</th>
                  <th>Why</th>
                  <th>Owner</th>
                </tr>
              </thead>
              <tbody>
                {a.checks.map((c) => (
                  <tr key={c.code}>
                    <td>{c.code.replaceAll("_", " ")}</td>
                    <td>{c.status}</td>
                    <td>{c.evidence_ref ?? "none"}</td>
                    <td>{c.reason}</td>
                    <td>{c.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
      <section aria-labelledby="attestations">
        <h2 id="attestations">Owner attestations (human decisions)</h2>
        <p>Each needs a reference to the evidence (a document, ticket or ledger entry). They expire after 90 days.</p>
        {body.attestations.length === 0 ? (
          <p>None recorded.</p>
        ) : (
          <ul aria-label="Attestations">
            {body.attestations.map((x) => (
              <li key={x.id}>
                {x.kind.replaceAll("_", " ")} · {x.evidence_ref} · {karachiTime(x.attested_at)}
                {x.current ? "" : " (expired)"}
              </li>
            ))}
          </ul>
        )}
        {owner ? <AttestForm /> : null}
      </section>
      <section aria-labelledby="pilot">
        <h2 id="pilot">Pilot authorization</h2>
        {body.authorizations.length === 0 ? (
          <p>No pilot has been authorized.</p>
        ) : (
          <ul aria-label="Pilot authorizations">
            {body.authorizations.map((x) => (
              <li key={x.id}>
                {x.status}
                {x.pause_reason ? ` (${x.pause_reason.replaceAll("_", " ")})` : ""} · {x.purpose} · at most {x.max_per_day} a day · until{" "}
                {karachiTime(x.expires_at)}
                {x.expired ? " (expired)" : ""}
                {owner && x.status !== "revoked" && !x.expired ? <AuthorizationActions id={x.id} status={x.status} /> : null}
              </li>
            ))}
          </ul>
        )}
        {owner && ready && live.length === 0 ? <AuthorizeForm assessmentId={a.id} acknowledgement={body.acknowledgement} /> : null}
        {owner && !ready ? <p>A pilot can be authorized only from a fresh assessment that is ready for owner review.</p> : null}
      </section>
      <section aria-labelledby="rollback">
        <h2 id="rollback">Stop and roll back</h2>
        <ol>
          <li>Pause or revoke the pilot above (takes effect on the next confirmation).</li>
          <li>Set HERMECIOUS_OUTREACH_KILL_SWITCH=true, or HERMECIOUS_LIVE_OUTBOUND_ENABLED=false, and restart.</li>
          <li>Messages Meta already accepted cannot be recalled; their history stays for investigation.</li>
          <li>Real customer replies appear in the read-only Inbox; a person answers them (no automated replies).</li>
        </ol>
      </section>
    </main>
  );
}
