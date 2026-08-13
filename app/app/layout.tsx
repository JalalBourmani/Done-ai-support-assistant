import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "./components/Sidebar";
import { getAgentStatus, getAllCases, getAssignedCases } from "@/lib/cases";

export const metadata: Metadata = {
  title: "Auto-XSALE",
  description: "Lokal saksassistent for XSALE-support",
};

/**
 * Sidebar counts, but never at the cost of rendering the shell.
 *
 * The layout wraps every route including the statically generated 404, so a
 * missing AUTO_XSALE_DIR here would fail `next build` before the user has had a
 * chance to configure anything. The counts degrade to zero; the data pages
 * still surface the real error, which is where it belongs.
 */
async function sidebarData() {
  try {
    const [cases, assigned, agent] = await Promise.all([
      getAllCases(),
      getAssignedCases(),
      getAgentStatus(),
    ]);
    return { cases, assigned, agentWorking: agent.state === "working" };
  } catch {
    return { cases: [], assigned: [], agentWorking: false };
  }
}

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { cases, assigned, agentWorking } = await sidebarData();

  const resolvedCount = cases.filter((c) => c.resolved).length;
  const awaitingCount = cases.filter((c) => c.awaiting).length;

  return (
    <html lang="nb">
      <body>
        <div className="app">
          <Sidebar
            counts={{
              // "Behandlede saker" = everything still needing attention, so
              // neither resolved nor parked awaiting the customer.
              cases: cases.length - resolvedCount - awaitingCount,
              assigned: assigned.length,
              awaiting: awaitingCount,
              resolved: resolvedCount,
            }}
            agentWorking={agentWorking}
          />
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
