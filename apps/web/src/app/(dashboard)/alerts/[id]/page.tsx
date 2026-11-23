import type { Metadata } from "next";

import { AlertDetail } from "@/features/alerts/components/alert-detail";
import { decodeParam } from "@/lib/route-params";

export const metadata: Metadata = { title: "Alert rule" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AlertDetail id={decodeParam(id)} />;
}
