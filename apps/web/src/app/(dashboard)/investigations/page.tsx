import type { Metadata } from "next";

import { InvestigationsScreen } from "@/features/investigations/components/investigations-screen";

export const metadata: Metadata = { title: "AI investigations" };

export default function Page() {
  return <InvestigationsScreen />;
}
