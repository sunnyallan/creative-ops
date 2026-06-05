"use client";
import { useState } from "react";
import { supabaseBrowser } from "@/lib/supabase";

export default function LoginPage() {
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
      <h1 className="text-2xl font-semibold">Sign in</h1>
      {sent ? (
        <p className="mt-4 text-neutral-700">Check your email for a magic link.</p>
      ) : (
        <form onSubmit={send} className="mt-6 space-y-3">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@brand.com"
            className="w-full rounded-md border px-3 py-2"
          />
          <button className="w-full rounded-md bg-neutral-900 px-4 py-2 text-white">
            Send magic link
          </button>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </form>
      )}
    </main>
  );
}
