import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ISB Research Explorer", template: "%s · ISB Research Explorer" },
  description:
    "Search ISB faculty research by topic, read plain-English summaries of their papers, and know what to ask them about.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
      </head>
      <body>
        <header className="topbar">
          <div className="wrap">
            <Link href="/" className="brand">
              <span className="mark">ISB</span> Research Explorer
            </Link>
            <nav className="nav">
              <Link href="/faculty">Faculty</Link>
              <Link href="/about">About</Link>
            </nav>
          </div>
        </header>
        <main>
          <div className="wrap">{children}</div>
        </main>
        <footer className="foot">
          <div className="wrap">
            Independent student project, not an official ISB site. Summaries are written from each paper&apos;s
            text and public sources — check the original paper before citing.
          </div>
        </footer>
      </body>
    </html>
  );
}
