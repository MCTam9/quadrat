import type { Metadata, Viewport } from "next";
import { Archivo } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";
import { CLERK_ENABLED } from "@/lib/env";
import { ClerkShell } from "@/components/ClerkShell";

// Variable Archivo with the width axis: expanded for the site name and figures, normal elsewhere.
const archivo = Archivo({ subsets: ["latin"], axes: ["wdth"], variable: "--font-archivo", display: "swap" });

export const metadata: Metadata = {
  title: "Quadrat",
  description: "Drop a square on any site, see its buildings, density, land use and climate, and download it as CAD.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={archivo.variable}>
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
