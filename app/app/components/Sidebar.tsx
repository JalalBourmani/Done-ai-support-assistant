"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  IconCheck,
  IconClock,
  IconDashboard,
  IconFolder,
  IconInbox,
  IconRobot,
} from "./Icons";

interface NavCounts {
  cases: number;
  assigned: number;
  awaiting: number;
  resolved: number;
}

export default function Sidebar({
  counts,
  agentWorking,
}: {
  counts: NavCounts;
  agentWorking: boolean;
}) {
  const pathname = usePathname();

  const items = [
    { href: "/", label: "Oversikt", Icon: IconDashboard, badge: null },
    { href: "/cases", label: "Behandlede saker", Icon: IconFolder, badge: counts.cases },
    { href: "/assigned", label: "Mine XSALE-saker", Icon: IconInbox, badge: counts.assigned },
    { href: "/awaiting", label: "Venter på svar", Icon: IconClock, badge: counts.awaiting },
    { href: "/resolved", label: "Løste saker", Icon: IconCheck, badge: counts.resolved },
    { href: "/agent", label: "Agent", Icon: IconRobot, badge: null },
  ];

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <aside className="sidebar">
      <Link href="/" className="brand">
        <div className="brand-mark">AX</div>
        <div>
          <div className="brand-name">Auto-XSALE</div>
          <div className="brand-sub">Saksassistent</div>
        </div>
      </Link>

      <div className="nav-label">Arbeidsflate</div>
      {items.map(({ href, label, Icon, badge }) => (
        <Link
          key={href}
          href={href}
          className={`nav-item ${isActive(href) ? "active" : ""}`}
        >
          <Icon className="ico" />
          <span>{label}</span>
          {badge != null && <span className="nav-badge">{badge}</span>}
        </Link>
      ))}

      <div className="sidebar-foot">
        <div className="row" style={{ gap: 8 }}>
          <span className={`pulse ${agentWorking ? "" : "standby"}`} />
          <span>{agentWorking ? "Agent jobber" : "Agent i standby"}</span>
        </div>
        <div style={{ marginTop: 8, opacity: 0.7 }}>Lokal · read-only</div>
      </div>
    </aside>
  );
}
