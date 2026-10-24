import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Every page is generated at build time from content/*.json; no server or database at runtime.
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
