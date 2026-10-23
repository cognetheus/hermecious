import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api/v1/* is proxied to the API
// so session cookies stay first-party and no CORS is needed (ADR-010).
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://api:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiInternalUrl}/api/v1/:path*` }];
  },
};

export default nextConfig;
