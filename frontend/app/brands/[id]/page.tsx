"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { useBrand, Brand } from "@/lib/brand-context";

export default function BrandEdit() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { refresh } = useBrand();

  const [b, setB] = useState<Brand | null>(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch<Brand>(`/brands/${id}`).then(setB).catch((e) => setErr(e.message));
  }, [id]);

  async function save() {
    if (!b) return;
    setSaving(true); setErr(null);
    try {
      await apiFetch(`/brands/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...b,
          asset_permission_accepted: true,
        }),
      });
      await refresh();
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!confirm("Delete this brand? Campaigns and creatives will keep their references but the brand goes away.")) return;
    await apiFetch(`/brands/${id}`, { method: "DELETE" });
    await refresh();
    router.push("/brands");
  }

  if (!b) return <main className="p-12">{err || "Loading…"}</main>;

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <Link href="/brands" className="text-sm text-blue-600">← All brands</Link>
      <h1 className="mt-2 text-3xl font-semibold">{b.name}</h1>

      <section className="mt-6 space-y-3">
        <h2 className="font-semibold">Basics</h2>
        <Input label="Name" v={b.name} on={(v) => setB({ ...b, name: v })} />
        <Input label="Tone" v={b.tone || ""} on={(v) => setB({ ...b, tone: v })} />
        <TextArea label="Brand values" v={b.brand_values || ""} on={(v) => setB({ ...b, brand_values: v })} />
      </section>

      <section className="mt-6 space-y-3">
        <h2 className="font-semibold">Colours</h2>
        <Colour label="Primary" v={b.primary_colour || ""} on={(v) => setB({ ...b, primary_colour: v })} />
        <Colour label="Secondary" v={b.secondary_colour || ""} on={(v) => setB({ ...b, secondary_colour: v })} />
        <Colour label="Accent" v={b.accent_colour || ""} on={(v) => setB({ ...b, accent_colour: v })} />
      </section>

      <section className="mt-6 space-y-3">
        <h2 className="font-semibold">Brand rules</h2>
        <TextArea label="What we CAN do" v={b.brand_rules_do || ""} on={(v) => setB({ ...b, brand_rules_do: v })} />
        <TextArea label="What we must AVOID" v={b.brand_rules_dont || ""} on={(v) => setB({ ...b, brand_rules_dont: v })} />
        <Input label="Feel" v={b.brand_feel || ""} on={(v) => setB({ ...b, brand_feel: v })} />
      </section>

      <section className="mt-6 space-y-3">
        <h2 className="font-semibold">Style description</h2>
        <p className="text-xs text-neutral-600">
          Auto-aggregated from your reference banners. Edit freely if you want to tweak — must stay 200+ chars (or you need ≥2 references).
          <Link href={`/brands/${id}/references`} className="ml-2 text-blue-600">Manage references →</Link>
        </p>
        <TextArea label="" v={b.style_description || ""} on={(v) => setB({ ...b, style_description: v })} rows={10} />
        <p className="text-xs text-neutral-500">{(b.style_description || "").trim().length} chars</p>
      </section>

      <div className="mt-8 flex items-center gap-3">
        <button onClick={save} disabled={saving} className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50">
          {saving ? "Saving…" : "Save brand"}
        </button>
        {saved && <span className="text-sm text-emerald-600">Saved</span>}
        <button onClick={remove} className="ml-auto rounded-md border border-red-300 px-4 py-2 text-sm text-red-600 hover:bg-red-50">
          Delete brand
        </button>
      </div>
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </main>
  );
}

function Input({ label, v, on }: { label: string; v: string; on: (v: string) => void }) {
  return (
    <label className="block text-sm">
      {label}
      <input value={v} onChange={(e) => on(e.target.value)} className="mt-1 w-full rounded-md border px-3 py-2" />
    </label>
  );
}
function TextArea({ label, v, on, rows = 3 }: { label: string; v: string; on: (v: string) => void; rows?: number }) {
  return (
    <label className="block text-sm">
      {label}
      <textarea value={v} onChange={(e) => on(e.target.value)} rows={rows} className="mt-1 w-full rounded-md border px-3 py-2" />
    </label>
  );
}
function Colour({ label, v, on }: { label: string; v: string; on: (v: string) => void }) {
  return (
    <div className="text-sm">
      <div>{label}</div>
      <div className="mt-1 flex items-center gap-2">
        <input type="color" value={v && v.startsWith("#") ? v : "#000000"}
          onChange={(e) => on(e.target.value)} className="h-9 w-12 rounded border" />
        <input value={v} onChange={(e) => on(e.target.value)} placeholder="#RRGGBB"
          className="w-32 rounded-md border px-3 py-2" />
      </div>
    </div>
  );
}
