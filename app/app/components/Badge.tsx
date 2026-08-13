import React from "react";
import { priorityBadge, statusBadge } from "@/lib/format";
import type { WorkState } from "@/lib/types";

export function Badge({
  color = "gray",
  children,
  dot = false,
}: {
  color?: "green" | "amber" | "red" | "blue" | "violet" | "gray";
  children: React.ReactNode;
  dot?: boolean;
}) {
  return (
    <span className={`badge badge-${color}`}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string | null }) {
  const { color, label } = statusBadge(status);
  return (
    <Badge color={color} dot>
      {label}
    </Badge>
  );
}

export function PriorityBadge({ priority }: { priority: string | null }) {
  const { color, label } = priorityBadge(priority);
  if (!priority) return <span className="muted">–</span>;
  return <Badge color={color}>{label}</Badge>;
}

/** The user's own workflow state, separate from the XSALE status. */
export function WorkStateBadge({ state }: { state: WorkState }) {
  if (state === "resolved") {
    return (
      <Badge color="green" dot>
        Løst
      </Badge>
    );
  }
  if (state === "awaiting") {
    return (
      <Badge color="violet" dot>
        Venter på tilbakemelding
      </Badge>
    );
  }
  return (
    <Badge color="amber" dot>
      Åpen
    </Badge>
  );
}

export function ProcessedBadge({ processed }: { processed: boolean }) {
  return processed ? (
    <Badge color="green" dot>
      Behandlet
    </Badge>
  ) : (
    <Badge color="amber" dot>
      Ubehandlet
    </Badge>
  );
}
