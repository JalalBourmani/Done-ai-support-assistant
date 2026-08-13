import { NextResponse } from "next/server";
import { getCaseSummary } from "@/lib/cases";
import { setAwaiting } from "@/lib/store";

export const dynamic = "force-dynamic";

// Park a case as "waiting for customer feedback".
// Optional JSON body: { note: string } — a short reminder of what we're waiting for.
export async function POST(
  req: Request,
  { params }: { params: { caseNumber: string } },
) {
  const summary = await getCaseSummary(params.caseNumber);
  if (!summary) {
    return NextResponse.json({ error: "Case not found" }, { status: 404 });
  }

  let note: string | undefined;
  try {
    const body = await req.json();
    if (body && typeof body.note === "string") note = body.note;
  } catch {
    // No body is fine — the note is optional.
  }

  try {
    const entry = await setAwaiting(params.caseNumber, true, { note });
    return NextResponse.json({
      caseNumber: params.caseNumber,
      awaiting: true,
      awaitingSince: entry?.since ?? null,
      awaitingNote: entry?.note ?? null,
      // Setting this state clears "resolved" — say so, so the client can trust it.
      resolved: false,
    });
  } catch {
    return NextResponse.json({ error: "Kunne ikke lagre status" }, { status: 500 });
  }
}

// Un-park a case (back to open).
export async function DELETE(
  _req: Request,
  { params }: { params: { caseNumber: string } },
) {
  try {
    await setAwaiting(params.caseNumber, false);
    return NextResponse.json({
      caseNumber: params.caseNumber,
      awaiting: false,
      awaitingSince: null,
      awaitingNote: null,
    });
  } catch {
    return NextResponse.json({ error: "Kunne ikke lagre status" }, { status: 500 });
  }
}
