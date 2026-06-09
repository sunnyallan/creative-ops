"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Legacy onboarding URL — redirects to the new brand creation wizard.
export default function OnboardingRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/brands/new");
  }, [router]);
  return <main className="p-12">Redirecting…</main>;
}
