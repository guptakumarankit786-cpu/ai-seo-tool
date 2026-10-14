import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI SEO Tool",
  description: "AI-powered SEO workspace",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col font-sans md:flex-row">
        <aside className="border-b border-border bg-surface md:min-h-screen md:w-56 md:border-b-0 md:border-r">
          <div className="flex items-center gap-4 px-4 py-3 md:flex-col md:items-stretch md:gap-1 md:py-5">
            <Link href="/" className="text-sm font-semibold tracking-tight md:mb-4 md:px-2">
              AI SEO Tool
            </Link>
            <Link
              href="/integrations"
              className="rounded-md px-2 py-1.5 text-sm text-muted hover:bg-accent-soft hover:text-foreground"
            >
              Integrations
            </Link>
          </div>
        </aside>
        <main className="flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </body>
    </html>
  );
}
