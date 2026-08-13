import { NextResponse } from "next/server";
import { getAllCases, getRootDir } from "@/lib/cases";

export const dynamic = "force-dynamic";

export async function GET() {
  const cases = await getAllCases();
  return NextResponse.json({ root: getRootDir(), count: cases.length, cases });
}
