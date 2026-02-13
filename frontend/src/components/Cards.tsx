import Link from "next/link";
import type { ReactNode } from "react";

export function PageContainer({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main style={{ padding: 24, fontFamily: "Arial, sans-serif", maxWidth: 900, margin: "0 auto" }}>
      <h1>{title}</h1>
      <nav style={{ marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap" }}>
        <Link href="/">Home</Link>
        <Link href="/proposals">Proposals</Link>
        <Link href="/projects">Projects</Link>
        <Link href="/projects/capital">Project Capital</Link>
        <Link href="/agents">Agents</Link>
        <Link href="/bounties">Bounties</Link>
        <Link href="/settlement">Settlement</Link>
        <Link href="/reputation">Reputation</Link>
        <Link href="/discussions">Discussions</Link>
      </nav>
      {children}
    </main>
  );
}

export function DataCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 12 }}>
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      {children}
    </section>
  );
}
