import type { NextConfig } from "next";
import { config as loadEnv } from "dotenv";
import path from "node:path";

// Same resolution as scripts/check-clerk-env.mjs (root .env, then frontend/.env.local)
loadEnv({ path: path.resolve(process.cwd(), "..", ".env") });
loadEnv({
  path: path.resolve(process.cwd(), ".env.local"),
  override: !process.env.NEXT_PUBLIC_API_URL,
});

const nextConfig: NextConfig = {
  output: "export",
};

export default nextConfig;
