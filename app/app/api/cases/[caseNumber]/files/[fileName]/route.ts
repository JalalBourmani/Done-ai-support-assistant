import { NextResponse } from "next/server";
import { readCaseFileContent, readCaseFileRaw } from "@/lib/cases";

export const dynamic = "force-dynamic";

/**
 * Build an RFC 6266 Content-Disposition value that survives Norwegian
 * filenames. The quoted ASCII form is the fallback for old clients; the
 * `filename*` form is what modern browsers actually use.
 */
function contentDisposition(name: string, attachment: boolean): string {
  const ascii = name.replace(/[^\x20-\x7e]/g, "_").replace(/["\\]/g, "_");
  // encodeURIComponent leaves !'()* alone, but RFC 5987 attr-char excludes
  // them — percent-encode those too or a filename with an apostrophe
  // ("Ordre_Bjørn's.pdf") produces a header the browser reads as terminated.
  const encoded = encodeURIComponent(name).replace(
    /['()!*]/g,
    (c) => "%" + c.charCodeAt(0).toString(16).toUpperCase(),
  );
  const kind = attachment ? "attachment" : "inline";
  return `${kind}; filename="${ascii}"; filename*=UTF-8''${encoded}`;
}

export async function GET(
  req: Request,
  { params }: { params: { caseNumber: string; fileName: string } },
) {
  const url = new URL(req.url);
  const wantsRaw = url.searchParams.get("raw") === "1";
  const wantsDownload = url.searchParams.get("download") === "1";

  try {
    const fileName = decodeURIComponent(params.fileName);

    if (!wantsRaw) {
      const file = await readCaseFileContent(params.caseNumber, fileName);
      if (!file) {
        return NextResponse.json({ error: "File not found" }, { status: 404 });
      }
      return NextResponse.json(file);
    }

    const raw = await readCaseFileRaw(params.caseNumber, fileName);
    if (!raw) {
      return NextResponse.json({ error: "File not found" }, { status: 404 });
    }

    // Case folders are edited by the agent while the UI is open, so the bytes
    // must be revalidated every time. An mtime+size ETag makes that revalidation
    // a 304 instead of re-sending a few megabytes each time the lightbox opens.
    const etag = `"${raw.size}-${raw.modified.getTime()}"`;
    const headers: Record<string, string> = {
      "Content-Type": raw.mime,
      "Content-Length": String(raw.size),
      "Content-Disposition": contentDisposition(raw.name, wantsDownload),
      "Cache-Control": "private, max-age=0, must-revalidate",
      ETag: etag,
      "Last-Modified": raw.modified.toUTCString(),
      // These files arrive as customer e-mail attachments. nosniff stops a
      // mislabelled file being treated as HTML, and the CSP neutralises script
      // inside an SVG if the URL is ever opened directly in a tab.
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy":
        "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox",
    };

    if (req.headers.get("if-none-match") === etag) {
      return new NextResponse(null, { status: 304, headers });
    }

    return new NextResponse(raw.bytes, { status: 200, headers });
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }
}
