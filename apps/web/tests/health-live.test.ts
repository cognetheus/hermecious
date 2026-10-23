import { describe, expect, it } from "vitest";

import * as route from "../app/health/live/route";

describe("GET /health/live", () => {
  it("answers alive with no-store", async () => {
    const response = route.GET();
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ status: "alive" });
  });

  it("is rendered per request, never prerendered at build time", () => {
    expect(route.dynamic).toBe("force-dynamic");
  });
});
