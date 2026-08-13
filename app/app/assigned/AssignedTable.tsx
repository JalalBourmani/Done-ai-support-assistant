"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { AssignedCase } from "@/lib/types";
import { formatDate } from "@/lib/format";
import { PriorityBadge, StatusBadge } from "../components/Badge";
import { IconExternal } from "../components/Icons";

export default function AssignedTable({ cases }: { cases: AssignedCase[] }) {
  const [q, setQ] = useState("");
  const [onlyOpen, setOnlyOpen] = useState(false);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return cases.filter((c) => {
      if (onlyOpen && c.processed) return false;
      if (!needle) return true;
      return (
        c.caseNumber.includes(needle) ||
        (c.customer || "").toLowerCase().includes(needle) ||
        (c.subject || "").toLowerCase().includes(needle)
      );
    });
  }, [cases, q, onlyOpen]);

  return (
    <div className="panel">
      <div className="panel-head" style={{ gap: 12, flexWrap: "wrap" }}>
        <div className="btn-row">
          <button
            className={`btn ${!onlyOpen ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setOnlyOpen(false)}
          >
            Alle <span style={{ opacity: 0.7 }}>{cases.length}</span>
          </button>
          <button
            className={`btn ${onlyOpen ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setOnlyOpen(true)}
          >
            Gjenstår <span style={{ opacity: 0.7 }}>{cases.filter((c) => !c.processed).length}</span>
          </button>
        </div>
        <input
          className="btn btn-ghost"
          style={{ minWidth: 240, cursor: "text" }}
          placeholder="Søk saksnr, kunde, emne…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Sak</th>
              <th>Kunde</th>
              <th>Emne</th>
              <th>Status</th>
              <th>Prioritet</th>
              <th>Opprettet</th>
              <th>Agent</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted" style={{ textAlign: "center", padding: 30 }}>
                  Ingen saker matcher.
                </td>
              </tr>
            )}
            {rows.map((c) => (
              <tr key={c.caseNumber}>
                <td className="case-num">{c.caseNumber}</td>
                <td className="truncate">{c.customer || <span className="muted">–</span>}</td>
                <td className="truncate dim">{c.subject || <span className="muted">–</span>}</td>
                <td><StatusBadge status={c.status} /></td>
                <td><PriorityBadge priority={c.priority} /></td>
                <td className="dim">{formatDate(c.created)}</td>
                <td>
                  {c.resolved ? (
                    <span className="badge badge-green"><span className="dot" />Løst</span>
                  ) : c.awaiting ? (
                    <span className="badge badge-violet"><span className="dot" />Venter på svar</span>
                  ) : c.processed ? (
                    <span className="badge badge-blue"><span className="dot" />Behandlet</span>
                  ) : (
                    <span className="badge badge-amber"><span className="dot" />Gjenstår</span>
                  )}
                </td>
                <td>
                  {c.hasLocalFolder ? (
                    <Link href={`/cases/${c.caseNumber}`} className="btn btn-ghost" style={{ padding: "4px 9px" }}>
                      <IconExternal width={14} height={14} /> Åpne
                    </Link>
                  ) : (
                    <span className="muted" style={{ fontSize: 12 }}>ingen mappe</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
