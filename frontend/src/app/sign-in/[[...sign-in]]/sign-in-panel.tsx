"use client";

import { SignIn } from "@clerk/clerk-react";

export function SignInPanel() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <SignIn routing="hash" />
    </div>
  );
}
