"use client";

import { SignUp } from "@clerk/clerk-react";

export function SignUpPanel() {
  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50">
      <SignUp routing="hash" />
    </div>
  );
}
