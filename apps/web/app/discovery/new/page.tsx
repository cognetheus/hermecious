import Link from "next/link";
import { redirect } from "next/navigation";

import { apiGet, type CurrentUser } from "../../../lib/api";
import type { SourceOption } from "../../../lib/discovery";
import NewRunForm, { type SeedImport } from "./new-run-form";

export const dynamic = "force-dynamic";

type Ceilings = { max_candidates: number; max_search_pages: number; max_fetches: number; max_seconds: number };

export default async function NewRunPage() {
  const [{ body: me }, sources, imports] = await Promise.all([
    apiGet<CurrentUser>("/api/v1/auth/me"),
    apiGet<{ sources: SourceOption[]; budget_ceilings: Ceilings; city: string }>("/api/v1/discovery/sources"),
    apiGet<{ items: SeedImport[] }>("/api/v1/discovery/seed-imports"),
  ]);
  if (me.role === "observer") {
    redirect("/discovery");
  }
  return (
    <main>
      <p>
        <Link href="/discovery">All discovery runs</Link>
      </p>
      <h1>New discovery run</h1>
      {sources.body.sources.length === 0 ? (
        <p role="alert">
          No source is permitted right now. A live source needs a recorded owner rights review (see the discovery
          sources runbook).
        </p>
      ) : (
        <NewRunForm sources={sources.body.sources} ceilings={sources.body.budget_ceilings} city={sources.body.city} seedImports={imports.body.items} />
      )}
    </main>
  );
}
