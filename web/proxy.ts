import { NextResponse } from "next/server";
import type { NextFetchEvent, NextRequest } from "next/server";
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isPublic = createRouteMatcher(["/sign-in(.*)"]);

const withClerk = clerkMiddleware(async (auth, req) => {
  if (!isPublic(req)) await auth.protect();
});

export default function proxy(req: NextRequest, evt: NextFetchEvent) {
  // Auth disabled when no Clerk key is configured (local dev).
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) return NextResponse.next();
  return withClerk(req, evt);
}

export const config = {
  // Skip Next internals, static files and /api (the Python API verifies tokens itself).
  matcher: ["/((?!_next|api|.*\\.(?:ico|png|jpg|jpeg|svg|webp|woff2?|txt|json)$).*)"],
};
