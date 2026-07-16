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
        router.replace("/dashboard");
      } else {
        setChecking(false);
      }
    })();
  }, [router]);

  if (checking) {
    return <main className="p-12 text-muted">Loading…</main>;
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-20">
      <div className="chip chip-accent mb-6">v4.0 · Autonomous growth engine</div>
      <h1 className="text-5xl font-semibold tracking-tight text-fg">Creative Ops</h1>
      <p className="mt-4 text-lg text-muted max-w-xl">
        Set a goal and a budget. The system researches, generates on-brand creatives,
        publishes them, measures what works, learns, and iterates — until the goal is
        met or the budget is spent.
      </p>
      <div className="mt-8 flex gap-3">
        <Link href="/login" className="btn btn-primary">
          Sign in →
        </Link>
      </div>
    </main>
  );
}
