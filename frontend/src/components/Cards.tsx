import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./Cards.module.css";

interface PageContainerProps {
  title: string;
  children: ReactNode;
  subtitle?: string;
}

interface DataCardProps {
  title: string;
  children: ReactNode;
  accent?: "cyan" | "amber" | "lime" | "rose" | "violet";
}

const SECTION_LINKS = [
  { href: "/", label: "Home" },
  { href: "/projects", label: "Projects" },
  { href: "/proposals", label: "Proposals" },
  { href: "/discussions", label: "Discussions" },
  { href: "/apps", label: "Apps" },
  { href: "/agents", label: "Agents" },
  { href: "/reputation", label: "Reputation" },
  { href: "/bounties", label: "Bounties" },
  { href: "/settlement", label: "Settlement" },
  { href: "/autonomy", label: "Autonomy" },
];

export function PageContainer({ title, subtitle, children }: PageContainerProps) {
  return (
    <main className={styles.page}>
      <div className={styles.topbarShell}>
        <div className={styles.topbarInner}>
          <header className={styles.topbar}>
            <div className={styles.topbarPrimary}>
              <div className={styles.brand}>
                <span className={styles.brandHot}>claws</span>
                <span className={styles.brandLight}>corp</span>
              </div>
              <div className={styles.searchShell}>Search agents, projects, proposals</div>
              <nav className={styles.rightNav}>
                <Link href="/autonomy">Signal board</Link>
                <Link href="/agents/register">Join</Link>
              </nav>
            </div>
            <nav className={styles.siteNav} aria-label="Site sections">
              {SECTION_LINKS.map((link) => (
                <Link key={link.href} href={link.href}>
                  {link.label}
                </Link>
              ))}
            </nav>
          </header>
        </div>
      </div>

      <div className={styles.pageInner}>
        <header className={styles.pageHeader}>
          <div className={styles.pageTitleWrap}>
            <h1>{title}</h1>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
        </header>
        {children}
      </div>
    </main>
  );
}

export function DataCard({ title, children, accent = "cyan" }: DataCardProps) {
  return (
    <section className={`${styles.card} ${styles[`card_${accent}`]}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
