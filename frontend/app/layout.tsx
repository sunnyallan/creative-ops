import "./globals.css";
import type { Metadata } from "next";
import { Providers } from "@/components/providers";
import { TopNav } from "@/components/top-nav";

export const metadata: Metadata = { title: "Creative Ops", description: "AI Creative Operations" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <TopNav />
          {children}
        </Providers>
      </body>
    </html>
  );
}
