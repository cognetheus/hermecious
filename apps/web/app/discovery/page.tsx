import Link from "next/link";

import { karachiTime } from "../../lib/accounts";
import { apiGet, type CurrentUser } from "../../lib/api";
import { type Run, statusLabel } from "../../lib/discovery";

export const dynamic = "force-dynamic";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default async function DiscoveryPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const cursor = typeof params.cursor === "string" ? params.cursor : undefined;
  const [{ body: me }, list] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<{ items: Run[]; next_cursor: string | null; error?: { message: string } }>(
      `/api/v1/discovery/runs${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    ),
  ]);
  return (
    <main>
      <p>
        <Link href="/">Home</Link> · <Link href="/accounts">Accounts</Link>
      </p>
      <h1>Discovery runs</h1>
      <p>
        Each run takes at most 30 unverified listings from one permitted source. A run never covers every school in
        Lahore, and a listing is not a prospect until a reviewer admits it.
      </p>
      {me.role !== "observer" ? (
        <p>
          <Link href="/discovery/new">New discovery run</Link>
        </p>
      ) : null}
      {list.status !== 200 ? (
        <p role="alert">{list.body.error?.message ?? "Could not load runs"}</p>
      ) : list.body.items.length === 0 ? (
        <p>No discovery runs yet.</p>
      ) : (
        <table>
          <caption>Discovery runs, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Created (Asia/Karachi)</th>
              <th scope="col">Source</th>
              <th scope="col">Area</th>
              <th scope="col">Status</th>
              <th scope="col">Shown / examined</th>
              <th scope="col">Reviewed</th>
            </tr>
          </thead>
          <tbody>
            {list.body.items.map((run) => (
              <tr key={run.id}>
                <td>
                  <Link href={`/discovery/runs/${run.id}`}>{karachiTime(run.created_at)}</Link>
                </td>
                <td>
                  {run.provider}
                  {run.synthetic ? " (synthetic)" : ""}
                </td>
                <td>{run.area_label}</td>
                <td>{statusLabel(run)}</td>
                <td>
                  {run.displayed_count} / {run.examined_count}
                </td>
                <td>
                  {run.review_counts.accepted} accepted, {run.review_counts.rejected} rejected,{" "}
                  {run.review_counts.pending + run.review_counts.deferred} open
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {list.status === 200 && list.body.next_cursor ? (
        <p>
          <Link href={`/discovery?cursor=${encodeURIComponent(list.body.next_cursor)}`}>Older runs</Link>
        </p>
      ) : null}
    </main>
  );
}
