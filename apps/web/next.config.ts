import type { NextConfig } from "next";

// Browser requests to /api/* are proxied to the FastAPI service so the UI never needs CORS or
// hardcoded hosts. Server components call the API directly via API_INTERNAL_URL (see src/lib/api.ts).
const API = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8010";

const nextConfig: NextConfig = {
  output: "standalone",
  turbopack: { root: __dirname },
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
