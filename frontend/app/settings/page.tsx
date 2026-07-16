import Link from "next/link";

export default function SettingsHome() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="text-2xl font-semibold text-fg">Settings</h1>
      <p className="text-sm text-muted mt-0.5">
        Workspace-level configuration.
      </p>
      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Card href="/brands" title="Brands" desc="Colours, personas, references, rules" />
        <Card href="/settings/connections" title="Connections" desc="Meta / Instagram / Facebook page publishing" />
        <Card href="/settings/templates" title="Design templates" desc="Penpot-designed custom layouts with placeholders" />
        <Card href="/settings/template" title="Asset placement" desc="Default logo position, title bar, CTA style" />
        <Card href="/settings/channels" title="Channels" desc="Custom output sizes per channel" />
        <Card href="/settings/partners" title="Partners" desc="Reusable co-brand partners" />
      </div>
    </main>
  );
}

function Card({ href, title, desc }: { href: string; title: string; desc: string }) {
  return (
    <Link href={href} className="surface p-4 hover:border-strong transition">
      <div className="text-fg font-medium">{title}</div>
      <div className="text-sm text-muted mt-1">{desc}</div>
    </Link>
  );
}
