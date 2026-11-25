import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";
import { CLERK_ENABLED } from "@/lib/env";
import { ClerkShell } from "@/components/ClerkShell";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Site picker",
  description: "Pick a site, preview the buildings and analyse the context before you download CAD.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      {/* Browser extensions inject attributes on <body>; not our mismatch. */}
      <body suppressHydrationWarning>
        {CLERK_ENABLED ? (
          <ClerkProvider>
            <ClerkShell>{children}</ClerkShell>
          </ClerkProvider>
        ) : (
          children
        )}
      </body>
    </html>
  );
}
