import type { Metadata } from "next";

import { ErrorDetail } from "@/features/errors/components/error-detail";
import { decodeParam } from "@/lib/route-params";

export const metadata: Metadata = { title: "Error group" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ErrorDetail id={decodeParam(id)} />;
}
