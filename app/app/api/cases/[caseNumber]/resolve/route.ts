import { NextResponse } from "next/server";
import { getCaseSummary } from "@/lib/cases";
import { setResolved } from "@/lib/store";

export const dynamic = "force-dynamic";

// Mark a case as resolved.
export async function POST(
  _req: Request,
  { params }: { params: { caseNumber: string } },
) {
  const summary = await getCaseSummary(params.caseNumber);
  if (!summary) {
    return NextResponse.json({ error: "Case not found" }, { status: 404 });
  }
  try {
    const resolvedAt = await setResolved(params.caseNumber, true);
    return NextResponse.json({ caseNumber: params.caseNumber, resolved: true, resolvedAt });
  } catch {
    return NextResponse.json({ error: "Kunne ikke lagre status" }, { status: 500 });
  }
}

// Re-open a case (remove the resolved mark).
export async function DELETE(
  _req: Request,
  { params }: { params: { caseNumber: string } },
) {
  try {
    await setResolved(params.caseNumber, false);
    return NextResponse.json({ caseNumber: params.caseNumber, resolved: false, resolvedAt: null });
  } catch {
    return NextResponse.json({ error: "Kunne ikke lagre status" }, { status: 500 });
  }
}
