import fs from "node:fs/promises";
import path from "node:path";
import { getRootDir } from "./cases";
import type { WorkState } from "./types";

// UI-state lives in ONE hidden file at the root of the Auto-XSALE folder.
// This keeps the agent's case sub-folders strictly read-only while still
// letting the user persist workflow state. It sits with the data — not the app
// code — so it survives app re-copies.
//
// Three work states, mutually exclusive:
//   open      — nothing recorded (the default, no entry in either map)
//   awaiting  — answered, waiting for the customer to come back
//   resolved  — actually done
//
// The file format is additive: older files contain only `resolved`, and those
// keep working untouched. Setting one state always clears the other, so a case
// can never be in both maps at once.
const STORE_FILE = ".auto-xsale-ui.json";

interface ResolvedEntry {
  resolvedAt: string; // ISO
}

interface AwaitingEntry {
  since: string; // ISO — when it was parked
  note?: string; // optional short reminder of what we're waiting for
}

interface UiState {
  resolved: Record<string, ResolvedEntry>;
  awaiting: Record<string, AwaitingEntry>;
}

function storePath(): string {
  return path.join(getRootDir(), STORE_FILE);
}

export async function readUiState(): Promise<UiState> {
  try {
    const raw = await fs.readFile(storePath(), "utf-8");
    // Strip a UTF-8 BOM before parsing. Anything on Windows that touches this
    // file with a default text editor or PowerShell's Set-Content can add one,
    // and JSON.parse throws on it — which would silently reset every case back
    // to "open" without a word of warning. Cheap guard, nasty failure mode.
    const d = JSON.parse(raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw);
    return {
      resolved: d?.resolved && typeof d.resolved === "object" ? d.resolved : {},
      awaiting: d?.awaiting && typeof d.awaiting === "object" ? d.awaiting : {},
    };
  } catch {
    return { resolved: {}, awaiting: {} };
  }
}

async function writeUiState(state: UiState): Promise<void> {
  const tmp = storePath() + ".tmp";
  const data = JSON.stringify(state, null, 2);
  // Write to a temp file then rename for a more atomic update.
  await fs.writeFile(tmp, data, "utf-8");
  await fs.rename(tmp, storePath());
}

/** Map of caseNumber -> resolvedAt ISO string. */
export async function getResolvedMap(): Promise<Record<string, string>> {
  const state = await readUiState();
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(state.resolved)) {
    if (v && typeof v.resolvedAt === "string") out[k] = v.resolvedAt;
  }
  return out;
}

/** Map of caseNumber -> { since, note } for cases waiting on the customer. */
export async function getAwaitingMap(): Promise<
  Record<string, { since: string; note: string | null }>
> {
  const state = await readUiState();
  const out: Record<string, { since: string; note: string | null }> = {};
  for (const [k, v] of Object.entries(state.awaiting)) {
    if (v && typeof v.since === "string") {
      out[k] = { since: v.since, note: typeof v.note === "string" ? v.note : null };
    }
  }
  return out;
}

/** Mark / unmark a case as resolved. Clears "awaiting" if it was set. */
export async function setResolved(
  caseNumber: string,
  resolved: boolean,
  at?: string,
): Promise<string | null> {
  const state = await readUiState();
  // The two states are mutually exclusive.
  delete state.awaiting[caseNumber];

  if (resolved) {
    const resolvedAt = at ?? new Date().toISOString();
    state.resolved[caseNumber] = { resolvedAt };
    await writeUiState(state);
    return resolvedAt;
  }
  delete state.resolved[caseNumber];
  await writeUiState(state);
  return null;
}

/**
 * Mark / unmark a case as waiting for customer feedback. Clears "resolved" if
 * it was set — that is the whole point of this state existing: so a case that
 * is answered but not finished no longer has to be filed as done.
 */
export async function setAwaiting(
  caseNumber: string,
  awaiting: boolean,
  opts?: { at?: string; note?: string },
): Promise<{ since: string; note: string | null } | null> {
  const state = await readUiState();
  delete state.resolved[caseNumber];

  if (awaiting) {
    const since = opts?.at ?? new Date().toISOString();
    const note = opts?.note?.trim() ? opts.note.trim().slice(0, 200) : undefined;
    state.awaiting[caseNumber] = note ? { since, note } : { since };
    await writeUiState(state);
    return { since, note: note ?? null };
  }
  delete state.awaiting[caseNumber];
  await writeUiState(state);
  return null;
}

/** Derive the single work state for a case from the two maps. */
export function deriveWorkState(
  caseNumber: string,
  resolvedMap: Record<string, string>,
  awaitingMap: Record<string, { since: string; note: string | null }>,
): WorkState {
  if (resolvedMap[caseNumber]) return "resolved";
  if (awaitingMap[caseNumber]) return "awaiting";
  return "open";
}
