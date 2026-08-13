"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { formatDateTime, formatRelative } from "@/lib/format";
import type { WorkState } from "@/lib/types";
import { IconCheck, IconClock, IconRefresh } from "../../components/Icons";

/**
 * Three-state work control: open → awaiting feedback → resolved.
 *
 * "Venter på tilbakemelding" exists so a case that has been answered but is not
 * finished no longer has to be filed as resolved just to get it out of the way.
 */
export default function ResolveButton({
  caseNumber,
  workState,
  resolvedAt,
  awaitingSince,
  awaitingNote,
}: {
  caseNumber: string;
  workState: WorkState;
  resolvedAt: string | null;
  awaitingSince: string | null;
  awaitingNote: string | null;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<null | "resolve" | "await" | "reopen">(null);

  const call = async (
    kind: "resolve" | "await" | "reopen",
    endpoint: "resolve" | "awaiting",
    method: "POST" | "DELETE",
  ) => {
    setBusy(kind);
    try {
      await fetch(`/api/cases/${caseNumber}/${endpoint}`, {
        method,
        cache: "no-store",
      });
      router.refresh();
    } finally {
      setBusy(null);
    }
  };

  const markResolved = () => call("resolve", "resolve", "POST");
  const markAwaiting = () => call("await", "awaiting", "POST");
  const reopenFromResolved = () => call("reopen", "resolve", "DELETE");
  const reopenFromAwaiting = () => call("reopen", "awaiting", "DELETE");

  if (workState === "resolved") {
    return (
      <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
        <span className="badge badge-green" title={formatDateTime(resolvedAt)}>
          <IconCheck width={14} height={14} />
          Løst {resolvedAt ? `· ${formatDateTime(resolvedAt)}` : ""}
        </span>
        <button className="btn btn-ghost" onClick={markAwaiting} disabled={busy !== null}>
          <IconClock width={15} height={15} />
          {busy === "await" ? "…" : "Venter på tilbakemelding"}
        </button>
        <button className="btn btn-ghost" onClick={reopenFromResolved} disabled={busy !== null}>
          <IconRefresh width={15} height={15} />
          {busy === "reopen" ? "…" : "Gjenåpne"}
        </button>
      </div>
    );
  }

  if (workState === "awaiting") {
    return (
      <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
        <span
          className="badge badge-violet"
          title={awaitingNote || formatDateTime(awaitingSince)}
        >
          <IconClock width={14} height={14} />
          Venter på tilbakemelding
          {awaitingSince ? ` · ${formatRelative(awaitingSince)}` : ""}
        </span>
        <button className="btn btn-primary" onClick={markResolved} disabled={busy !== null}>
          <IconCheck width={16} height={16} />
          {busy === "resolve" ? "Lagrer…" : "Marker som løst"}
        </button>
        <button className="btn btn-ghost" onClick={reopenFromAwaiting} disabled={busy !== null}>
          <IconRefresh width={15} height={15} />
          {busy === "reopen" ? "…" : "Tilbake til åpen"}
        </button>
      </div>
    );
  }

  return (
    <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
      <button className="btn btn-primary" onClick={markResolved} disabled={busy !== null}>
        <IconCheck width={16} height={16} />
        {busy === "resolve" ? "Lagrer…" : "Marker som løst"}
      </button>
      <button className="btn btn-ghost" onClick={markAwaiting} disabled={busy !== null}>
        <IconClock width={15} height={15} />
        {busy === "await" ? "Lagrer…" : "Venter på tilbakemelding"}
      </button>
    </div>
  );
}
