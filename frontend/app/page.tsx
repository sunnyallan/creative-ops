import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-20">
      <h1 className="text-4xl font-semibold tracking-tight">Creative Ops</h1>
      <p className="mt-3 text-neutral-600">
        AI-native creative operations. Brief in, on-brand creatives out.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/login" className="rounded-md bg-neutral-900 px-4 py-2 text-white">Sign in</Link>
        <Link href="/onboarding" className="rounded-md border px-4 py-2">Onboarding</Link>
        <Link href="/campaigns/new" className="rounded-md border px-4 py-2">New campaign</Link>
        <Link href="/review" className="rounded-md border px-4 py-2">Review queue</Link>
        <Link href="/settings" className="rounded-md border px-4 py-2">Settings</Link>
      </div>
    </main>
  );
}
