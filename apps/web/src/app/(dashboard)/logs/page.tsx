import type { Metadata } from "next";

import { LogExplorer } from "@/features/logs/components/log-explorer";

export const metadata: Metadata = { title: "Log explorer" };

export default function Page() {
  return <LogExplorer />;
}
