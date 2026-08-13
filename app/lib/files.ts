/**
 * Pure file-type helpers.
 *
 * Deliberately free of `node:` imports so both the server (lib/cases.ts) and
 * the client components can share one source of truth for what counts as an
 * image. Duplicating the extension list in a client component is how the list
 * and the viewer drift apart.
 */

import type { FileKind } from "./types";

/** Lowercased extension including the dot, or "" when there is none. */
export function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  // A leading dot means a dotfile, not an extension.
  if (i <= 0) return "";
  return name.slice(i).toLowerCase();
}

/**
 * Image extensions we recognise, mapped to their MIME type.
 *
 * Recognising a format is not the same as being able to display it — see
 * `isDisplayableImage`. HEIC lives here so that a folder of straight-from-the-
 * iPhone photos is still labelled as images and offered for download, rather
 * than silently lumped in with binaries.
 */
export const IMAGE_MIME: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".jfif": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".avif": "image/avif",
  ".bmp": "image/bmp",
  ".ico": "image/x-icon",
  ".svg": "image/svg+xml",
  ".heic": "image/heic",
  ".heif": "image/heif",
  ".tif": "image/tiff",
  ".tiff": "image/tiff",
};

/**
 * Formats no mainstream desktop browser decodes. We still classify these as
 * images, but the UI offers a download instead of a broken-image icon.
 * `<img onError>` remains the backstop for anything corrupt or unexpected.
 */
const NOT_DISPLAYABLE = new Set([".heic", ".heif", ".tif", ".tiff"]);

const TEXT_MIME: Record<string, string> = {
  ".md": "text/markdown; charset=utf-8",
  ".markdown": "text/markdown; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".tsv": "text/tab-separated-values; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".log": "text/plain; charset=utf-8",
  ".pdf": "application/pdf",
};

export function kindForFile(name: string): FileKind {
  const ext = extOf(name);
  if (ext in IMAGE_MIME) return "image";
  if (ext === ".md" || ext === ".markdown") return "markdown";
  if (ext === ".json") return "json";
  if (ext === ".csv") return "csv";
  if (ext === ".txt" || ext === ".log" || ext === ".tsv") return "text";
  return "binary";
}

export function isImage(name: string): boolean {
  return extOf(name) in IMAGE_MIME;
}

/** True when the browser can be expected to actually paint this file. */
export function isDisplayableImage(name: string): boolean {
  const ext = extOf(name);
  return ext in IMAGE_MIME && !NOT_DISPLAYABLE.has(ext);
}

/**
 * MIME type for serving raw bytes.
 *
 * Anything unrecognised becomes `application/octet-stream` on purpose: this
 * server hands out attachments that arrived from customers by e-mail, and a
 * guessed `text/html` would let one of them run script on our own origin.
 */
export function mimeForFile(name: string): string {
  const ext = extOf(name);
  return IMAGE_MIME[ext] ?? TEXT_MIME[ext] ?? "application/octet-stream";
}

/** URL that streams the file's actual bytes (for `<img src>` / downloads). */
export function rawFileUrl(
  caseNumber: string,
  fileName: string,
  opts?: { download?: boolean },
): string {
  const base = `/api/cases/${encodeURIComponent(caseNumber)}/files/${encodeURIComponent(fileName)}`;
  return `${base}?raw=1${opts?.download ? "&download=1" : ""}`;
}
