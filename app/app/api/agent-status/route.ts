import { NextResponse } from "next/server";
import { getAgentStatus } from "@/lib/cases";

export const dynamic = "force-dynamic";

export async function GET() {
  const status = await getAgentStatus();
  return NextResponse.json(status);
}
