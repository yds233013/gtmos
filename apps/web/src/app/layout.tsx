import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { ModeBanner } from "@/components/shell/mode-banner";
import { Sidebar } from "@/components/shell/sidebar";
import { api } from "@/lib/api";
import type { Workspace } from "@/lib/types";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "GTMOS", template: "%s · GTMOS" },
  description: "AI-native revenue engine: target, enrich, score, research, route, sync and measure.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  let ws: Workspace | null = null;
  try {
    ws = await api<Workspace>("/workspace");
  } catch {
    ws = null;
  }
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
      <body className="min-h-screen font-sans text-sm">
        <div className="flex min-h-screen flex-col lg:flex-row">
          <Sidebar workspaceName={ws?.name ?? "GTMOS"} />
          <div className="flex min-w-0 flex-1 flex-col">
            <ModeBanner ws={ws} />
            <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 lg:px-8">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
