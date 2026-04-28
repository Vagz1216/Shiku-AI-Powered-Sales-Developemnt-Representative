import { SignInPanel } from "./sign-in-panel";

/** Required for `output: "export"` (S3 static hosting). */
export function generateStaticParams() {
  return [{ "sign-in": [] as string[] }];
}

export default function Page() {
  return <SignInPanel />;
}
