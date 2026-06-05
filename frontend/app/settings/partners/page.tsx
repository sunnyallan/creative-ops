"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { supabaseBrowser } from "@/lib/supabase";

type Partner = {
  id: string;
  name: string;
  logo_path: string | null;
  primary_colour: string | null;
  products_or_services: string | null;
};

export default function PartnersSettings() {
  const [list, setList] = useState<Partner[]>([]);
  const [draft, setDraft] = useState({ name: "", colour: "", products: "" });
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function refresh() {
    try { setList(await apiFetch<Partner[]>("/partners")); } catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { refresh(); }, []);

  async function uploadLogo(): Promise<string | null> {
    if (!logoFile) return null;
    const sb = supabaseBrowser();
    const { data: { user } } = await sb.auth.getUser();
    if (!user) throw new Error("not signed in");
    const path = `tenants/${user.id}/partners/${Date.now()}-${logoFile.name}`;
    const { error } = await sb.storage.from("tenant-assets").upload(path, logoFile, { upsert: true });
    if (error) throw error;
    return path;
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setErr(null);
    try {
      const logo_path = await uploadLogo();
      await apiFetch("/partners", {
        method: "POST",
        body: JSON.stringify({
          name: draft.name,
          logo_path,
          primary_colour: draft.colour || null,
          products_or_services: draft.products || null,
        }),
      });
      setDraft({ name: "", colour: "", products: "" });
      setLogoFile(null);
      refresh();
    } catch (e: any) { setErr(e.message); } finally { setSaving(false); }
  }

  async function remove(id: string) {
    if (!confirm("Delete this partner?")) return;
    await apiFetch(`/partners/${id}`, { method: "DELETE" });
    refresh();
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-3xl font-semibold">Partners</h1>
      <p className="mt-1 text-neutral-600">Reusable co-brand partners. Saved automatically when you create a campaign with a new partner.</p>

      <section className="mt-6 rounded-md border bg-white">
        {list.length === 0 ? (
          <p className="p-4 text-sm text-neutral-600">No partners yet. Add one below or create a campaign with a partner.</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 text-left">
              <tr><th className="px-3 py-2">Name</th><th>Products / services</th><th>Colour</th><th>Logo</th><th></th></tr>
            </thead>
            <tbody>
              {list.map((p) => (
                <tr key={p.id} className="border-t">
                  <td className="px-3 py-2 font-medium">{p.name}</td>
                  <td className="text-neutral-700">{p.products_or_services || <span className="text-neutral-400">—</span>}</td>
                  <td className="font-mono">{p.primary_colour || <span className="text-neutral-400">—</span>}</td>
                  <td>{p.logo_path ? "✓" : <span className="text-neutral-400">—</span>}</td>
                  <td><button onClick={() => remove(p.id)} className="text-xs text-red-600">remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="mt-8 rounded-md border bg-white p-4">
        <h2 className="font-semibold">Add / update partner</h2>
        <form onSubmit={save} className="mt-3 space-y-3">
          <label className="block text-sm">
            Name
            <input required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              placeholder="Cleartrip" className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block text-sm">
            What does this partner actually sell?
            <textarea value={draft.products} onChange={(e) => setDraft({ ...draft, products: e.target.value })}
              rows={2} placeholder="e.g. flights, hotels, trains, buses"
              className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block text-sm">
            Primary colour (hex)
            <input value={draft.colour} onChange={(e) => setDraft({ ...draft, colour: e.target.value })}
              placeholder="#FF6B35" className="mt-1 w-40 rounded-md border px-3 py-2" />
          </label>
          <label className="block text-sm">
            Logo (PNG/SVG)
            <input type="file" accept=".png,.svg" onChange={(e) => setLogoFile(e.target.files?.[0] || null)} className="mt-1 block" />
          </label>
          <button disabled={saving || !draft.name} className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50">
            {saving ? "Saving…" : "Save partner"}
          </button>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </form>
      </section>
    </main>
  );
}
