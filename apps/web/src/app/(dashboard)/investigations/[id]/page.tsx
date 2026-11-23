import type { Metadata } from "next";

import { InvestigationDetail } from "@/features/investigations/components/investigation-detail";
import { decodeParam } from "@/lib/route-params";

export const metadata: Metadata = { title: "Investigation" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvestigationDetail id={decodeParam(id)} />;
}
