"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { supabaseBrowser } from "@/lib/supabase";

export default function Home() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    (async () => {
      const sb = supabaseBrowser();
      const { data: { session } } = await sb.auth.getSession();
      if (session) {
        router.replace("/campaigns/new");
      } else {
        setChecking(false);
      }
    })();
  }, [router]);

  if (checking) return <main className="p-12">Loading…</main>;

  return (
    <main className="mx-auto max-w-3xl px-6 py-20">
      <h1 className="text-4xl font-semibold tracking-tight">Creative Ops</h1>
      <p className="mt-3 text-neutral-600">
        AI-native creative operations. Brief in, on-brand creatives out.
      </p>
      <div className="mt-8">
        <Link href="/login" className="rounded-md bg-neutral-900 px-4 py-2 text-white">
          Sign in
        </Link>
      </div>
    </main>
  );
}
