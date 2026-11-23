import type { Metadata } from "next";

import { ErrorsScreen } from "@/features/errors/components/errors-screen";

export const metadata: Metadata = { title: "Errors" };

export default function Page() {
  return <ErrorsScreen />;
}
