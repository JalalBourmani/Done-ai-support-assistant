// Pure formatting helpers — safe to use in both server and client components.

const MONTHS = [
  "jan", "feb", "mar", "apr", "mai", "jun",
  "jul", "aug", "sep", "okt", "nov", "des",
];

function pad(n: number): string {
  return n < 10 ? "0" + n : String(n);
}

/** "13. mai 2026, 10:14" */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return `${d.getDate()}. ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

/** "13. mai 2026" */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return `${d.getDate()}. ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

/** "for 3 dager siden" — relative, Norwegian. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "–";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "–";
  const diff = Date.now() - then;
  const abs = Math.abs(diff);
  const future = diff < 0;
  const mins = Math.round(abs / 60000);
  const hours = Math.round(abs / 3600000);
  const days = Math.round(abs / 86400000);

  let core: string;
  if (mins < 1) return future ? "straks" : "nettopp";
  if (mins < 60) core = `${mins} min`;
  else if (hours < 24) core = `${hours} ${hours === 1 ? "time" : "timer"}`;
  else if (days < 30) core = `${days} ${days === 1 ? "dag" : "dager"}`;
  else {
    const months = Math.round(days / 30);
    core = `${months} ${months === 1 ? "måned" : "måneder"}`;
  }
  return future ? `om ${core}` : `for ${core} siden`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

type BadgeColor = "green" | "amber" | "red" | "blue" | "violet" | "gray";

/** Map an XSALE status string to a badge colour + readable label. */
export function statusBadge(status: string | null): {
  color: BadgeColor;
  label: string;
} {
  const s = (status || "").toUpperCase();
  switch (s) {
    case "NEW":
      return { color: "blue", label: "Ny" };
    case "ASSIGNED":
      return { color: "violet", label: "Tildelt" };
    case "IN_PROGRESS":
    case "INPROGRESS":
    case "ONGOING":
      return { color: "amber", label: "Pågår" };
    case "WAITING":
    case "ON_HOLD":
    case "PENDING":
      return { color: "violet", label: "Venter" };
    case "RESOLVED":
    case "CLOSED":
    case "DONE":
      return { color: "green", label: "Løst" };
    case "":
      return { color: "gray", label: "Ukjent" };
    default:
      return { color: "gray", label: status as string };
  }
}

export function priorityBadge(priority: string | null): {
  color: BadgeColor;
  label: string;
} {
  const p = (priority || "").toUpperCase();
  switch (p) {
    case "HIGH":
    case "URGENT":
    case "CRITICAL":
      return { color: "red", label: "Høy" };
    case "NORMAL":
    case "MEDIUM":
      return { color: "gray", label: "Normal" };
    case "LOW":
      return { color: "gray", label: "Lav" };
    default:
      return { color: "gray", label: priority || "–" };
  }
}
