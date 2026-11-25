"use client";

import { useAuth, UserButton, Show } from "@clerk/nextjs";
import { useCallback } from "react";
import { TokenContext } from "@/lib/auth";

export function ClerkShell({ children }: { children: React.ReactNode }) {
  const { getToken } = useAuth();
  const get = useCallback(() => getToken(), [getToken]);
  return (
    <TokenContext.Provider value={get}>
      {children}
      <Show when="signed-in">
        <div className="fixed left-[21.75rem] top-4 z-30 hidden sm:block">
          <UserButton />
        </div>
      </Show>
    </TokenContext.Provider>
  );
}
