import Link from "next/link";

export default function SettingsHome() {
  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-3xl font-semibold">Settings</h1>
      <div className="mt-6 space-y-3">
        <Card href="/settings/template" title="Template" desc="Logo position, title bar, CTA style" />
        <Card href="/settings/channels" title="Channels" desc="Custom sizes per channel" />
        <Card href="/settings/partners" title="Partners" desc="Reusable co-brand partners" />
        <Card href="/onboarding" title="Brand kit" desc="Brand name, colours, fonts, personas" />
      </div>
    </main>
  );
}

function Card({ href, title, desc }: { href: string; title: string; desc: string }) {
  return (
    <Link href={href} className="block rounded-lg border bg-white p-4 hover:bg-neutral-50">
      <div className="font-medium">{title}</div>
      <div className="text-sm text-neutral-600">{desc}</div>
    </Link>
  );
}
