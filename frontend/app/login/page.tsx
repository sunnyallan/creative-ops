"use client";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { supabaseBrowser } from "@/lib/supabase";

export const dynamic = "force-dynamic";

function LoginInner() {
  const params = useSearchParams();
  const forbidden = params.get("forbidden") === "1";
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const sb = supabaseBrowser();
    const { error } = await sb.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${location.origin}/onboarding` },
    });
    if (error) setErr(error.message);
    else setSent(true);
  }

  return (
    <main className="mx-auto max-w-md px-6 py-20">
      <h1 className="text-2xl font-semibold text-fg">Sign in</h1>
      <p className="text-sm text-muted mt-1">Magic link — enter your email and we'll send you a one-click sign-in.</p>

      {forbidden && (
        <div className="mt-4 chip chip-danger">
          That email isn't allowed on this workspace. Contact the owner if you should have access.
        </div>
      )}

      {sent ? (
        <p className="mt-4 text-fg">Check your email for a magic link.</p>
      ) : (
        <form onSubmit={send} className="mt-6 space-y-3">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@brand.com"
            className="input"
          />
          <button className="btn btn-primary w-full">Send magic link</button>
          {err && <p className="text-sm text-danger-fg">{err}</p>}
        </form>
      )}
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="p-12 text-muted">Loading…</main>}>
      <LoginInner />
    </Suspense>
  );
}
