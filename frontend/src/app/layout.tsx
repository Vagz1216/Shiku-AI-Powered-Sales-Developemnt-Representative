import type { Metadata } from "next";
import { ClerkAppProvider } from "@/components/clerk-app-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "SDR AI Platform",
  description: "Agent-Driven Outreach Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col" suppressHydrationWarning>
        <ClerkAppProvider>{children}</ClerkAppProvider>
      </body>
    </html>
  );
}
