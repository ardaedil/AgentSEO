import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {title: "AgentSEO", description: "Behavioral compatibility CI for agent-facing APIs"};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>
    <header className="border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-3 font-bold"><span className="grid h-9 w-9 place-items-center rounded-xl bg-ink text-white">A</span><span>AgentSEO</span><span className="rounded-full bg-indigo-50 px-2 py-1 text-[10px] uppercase tracking-wider text-accent">Compatibility CI</span></Link>
        <nav className="flex items-center gap-6 text-sm text-slate-600"><Link href="/">Dashboard</Link><Link href="/compatibility">Compatibility runs</Link><a href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/docs`} target="_blank">API Docs</a><Link href="/projects/new" className="btn-primary">New project</Link></nav>
      </div>
    </header>
    <main className="mx-auto max-w-7xl px-6 py-10">{children}</main>
  </body></html>;
}

