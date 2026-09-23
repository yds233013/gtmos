import type { NextConfig } from "next";

// Browser requests to /api/* are proxied to the FastAPI service so the UI never needs CORS or
// hardcoded hosts. Server components call the API directly via API_INTERNAL_URL (see src/lib/api.ts).
const API = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: { root: __dirname },
  // The Makefile, the README and the Playwright default all address the dev server as 127.0.0.1, but
  // `next dev` only trusts localhost by default: the HMR handshake is rejected, the client never
  // hydrates, and the page renders as a server-side shell where no tab, chart or form works. Failing
  // silently and only in development is the worst version of that bug, so both hosts are trusted.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${API}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
