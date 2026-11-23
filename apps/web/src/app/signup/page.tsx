import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthScreen } from "@/features/auth/components/auth-screen";

export const metadata: Metadata = { title: "Create an organization" };

export default function SignupPage() {
  return (
    <Suspense>
      <AuthScreen mode="signup" />
    </Suspense>
  );
}
