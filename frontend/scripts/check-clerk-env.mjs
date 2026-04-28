/**
 * Fail fast if Clerk publishable key is missing or looks like a placeholder.
 * Load the same env files as next.config.ts (repo root .env, then frontend/.env.local).
 */
import { config } from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");

config({ path: path.resolve(frontendRoot, "..", ".env") });
config({ path: path.resolve(frontendRoot, ".env.local"), override: true });

const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY?.trim();
const looksReal =
  key &&
  /^pk_(test|live)_[A-Za-z0-9_-]+$/.test(key) &&
  key.length >= 32 &&
  !key.includes("...");

if (!looksReal) {
  const localPath = path.resolve(frontendRoot, ".env.local");
  console.error(`
Clerk: NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is missing or invalid.

Use the full Publishable key from the same Clerk application as your backend
(Clerk Dashboard → API Keys → "Publishable key").

Common mistake: ${localPath} is loaded AFTER repo root .env and overrides it.
If that file contains NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_... (ellipsis placeholder),
remove that line or replace it with the full key — otherwise it overwrites a good root .env.

Set the full key in repo root .env and/or frontend/.env.local (not "pk_test_..." truncated).
`);
  process.exit(1);
}
