import type { Metadata } from "next";

import { LiveLogs } from "@/features/live/components/live-logs";

export const metadata: Metadata = { title: "Live logs" };

export default function Page() {
  return <LiveLogs />;
}
