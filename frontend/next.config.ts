import type { NextConfig } from "next";

const pollMs = Number(process.env.NEXT_DEV_POLL_MS) || undefined;

const nextConfig: NextConfig = {
  cacheComponents: true,
  // Set by docker-compose: Windows bind mounts don't deliver file-change events.
  ...(pollMs && { watchOptions: { pollIntervalMs: pollMs } }),
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
