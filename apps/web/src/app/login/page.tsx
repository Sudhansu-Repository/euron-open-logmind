import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthScreen } from "@/features/auth/components/auth-screen";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <Suspense>
      <AuthScreen mode="login" />
    </Suspense>
  );
}
