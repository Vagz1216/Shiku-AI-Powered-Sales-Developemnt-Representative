import { SignUpPanel } from "./sign-up-panel";

/** Required for `output: "export"` (S3 static hosting). */
export function generateStaticParams() {
  return [{ "sign-up": [] as string[] }];
}

export default function Page() {
  return <SignUpPanel />;
}
