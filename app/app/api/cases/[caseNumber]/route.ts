import { NextResponse } from "next/server";
import { getCaseDetail } from "@/lib/cases";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: { caseNumber: string } },
) {
  const detail = await getCaseDetail(params.caseNumber);
  if (!detail) {
    return NextResponse.json({ error: "Case not found" }, { status: 404 });
  }
  return NextResponse.json(detail);
}
