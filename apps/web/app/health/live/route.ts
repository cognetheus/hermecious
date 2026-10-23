// Web server liveness only: answers when the Next.js server can serve a
// request. It does not check the API or any other dependency.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "alive" }, { headers: { "Cache-Control": "no-store" } });
}
