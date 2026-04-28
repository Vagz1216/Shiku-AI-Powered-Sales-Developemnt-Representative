"use client";

import { ClerkProvider } from "@clerk/clerk-react";

export function ClerkAppProvider({ children }: { children: React.ReactNode }) {
  const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  if (!key) {
    console.error("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is not set");
  }
  return (
    <ClerkProvider publishableKey={key ?? ""}>{children}</ClerkProvider>
  );
}
