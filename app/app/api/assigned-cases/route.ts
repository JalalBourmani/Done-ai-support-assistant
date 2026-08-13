import { NextResponse } from "next/server";
import { getAssignedCases } from "@/lib/cases";

export const dynamic = "force-dynamic";

export async function GET() {
  const cases = await getAssignedCases();
  return NextResponse.json({
    // When a live XSALE MCP/API is wired up, swap the source here.
    source: "local-snapshot",
    count: cases.length,
    cases,
  });
}
