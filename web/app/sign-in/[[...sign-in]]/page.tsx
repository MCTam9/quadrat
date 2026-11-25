import { SignIn } from "@clerk/nextjs";
import { CLERK_ENABLED } from "@/lib/env";

export default function Page() {
  if (!CLERK_ENABLED) {
    return <p className="p-8 text-sm text-muted">Auth is disabled (no Clerk key configured).</p>;
  }
  return (
    <main className="flex h-full items-center justify-center overflow-auto p-6">
      <SignIn />
    </main>
  );
}
