"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

type Template = {
  id: string;
  name: string;
  penpot_file_id: string | null;
  sync_status: "pending" | "synced" | "failed";
  sync_error: string | null;
  preview_url: string | null;
  zones: Record<string, unknown> | null;
  last_synced_at: string | null;
};

const PENPOT_URL = process.env.NEXT_PUBLIC_PENPOT_URL || "";

export default function TemplatesSettings() {
  const [list, setList] = useState<Template[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // Register form
  const [name, setName] = useState("");
  const [penpotUrl, setPenpotUrl] = useState("");
  const [boardName, setBoardName] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    try {
      setList(await apiFetch<Template[]>("/templates"));
    } catch (e: any) {
      setErr(e.message);
    }
  }
  useEffect(() => { load(); }, []);

  // Poll while any syncs are pending (same pattern as brand references)
  useEffect(() => {
    if (!list.some((t) => t.sync_status === "pending")) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [list]);

  async function register(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setErr(null);
    try {
      await apiFetch("/templates", {
        method: "POST",
        body: JSON.stringify({ name, penpot_url: penpotUrl, board_name: boardName }),
      });
      setName(""); setPenpotUrl(""); setBoardName("");
      load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  async function resync(id: string) {
    await apiFetch(`/templates/${id}/sync`, { method: "POST" });
    load();
  }

  async function remove(id: string) {
    if (!confirm("Delete this template? Campaigns that used it keep their creatives.")) return;
    await apiFetch(`/templates/${id}`, { method: "DELETE" });
    load();
  }

  function zoneKeys(t: Template): string[] {
    return Object.keys(t.zones || {}).filter((k) => !k.startsWith("_"));
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <Link href="/settings" className="text-sm text-blue-600">← Settings</Link>
      <div className="mt-2 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Templates</h1>
          <p className="mt-1 text-neutral-600">
            Design boards in Penpot with placeholder layers, register them here, and every campaign
            can render straight into your design.
          </p>
        </div>
        {PENPOT_URL && (
          <a href={PENPOT_URL} target="_blank" rel="noreferrer"
            className="shrink-0 rounded-md bg-neutral-900 px-4 py-2 text-sm text-white">
            Open Penpot ↗
          </a>
        )}
      </div>

      <details className="mt-4 rounded-md border bg-white p-4 text-sm">
        <summary className="cursor-pointer font-medium">How to design a template (placeholder convention)</summary>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-neutral-700">
          <li>In Penpot, create a board at your target size (e.g. 1080×1080) and give it a memorable name.</li>
          <li>Name layers with placeholders: <code>#headline</code>, <code>#body</code>, <code>#cta</code> (text),{" "}
            <code>#image</code> / <code>#image2</code>… (generated imagery), <code>#logo</code>,{" "}
            <code>#partner_logo</code>, <code>#slide_pip</code> (carousel “2/5”).</li>
          <li>Everything else renders exactly as designed — static brand decoration is yours.</li>
          <li>Use <b>Geist</b> or <b>DejaVu Sans</b> fonts so the renderer matches what you see.</li>
          <li>Copy the browser URL from the Penpot workspace and paste it below with the board name.</li>
        </ol>
      </details>

      <section className="mt-6 rounded-md border bg-white p-4">
        <h2 className="font-semibold">Register a template</h2>
        <form onSubmit={register} className="mt-3 grid grid-cols-1 gap-3">
          <label className="block text-sm">
            Template name
            <input required value={name} onChange={(e) => setName(e.target.value)}
              placeholder="IG Post — Product Hero v1"
              className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block text-sm">
            Penpot workspace URL (must contain file-id=…)
            <input required value={penpotUrl} onChange={(e) => setPenpotUrl(e.target.value)}
              placeholder="https://…/#/workspace?team-id=…&file-id=…&page-id=…"
              className="mt-1 w-full rounded-md border px-3 py-2 font-mono text-xs" />
          </label>
          <label className="block text-sm">
            Board name (exactly as in Penpot)
            <input required value={boardName} onChange={(e) => setBoardName(e.target.value)}
              placeholder="IG Post v1"
              className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <div>
            <button disabled={saving}
              className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50">
              {saving ? "Registering…" : "Register + sync"}
            </button>
          </div>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </form>
      </section>

      <section className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {list.map((t) => (
          <article key={t.id} className="rounded-lg border bg-white overflow-hidden">
            {t.preview_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={t.preview_url} alt="" className="w-full aspect-square object-contain bg-neutral-100" />
            ) : (
              <div className="aspect-square bg-neutral-100 grid place-items-center text-sm text-neutral-400">
                {t.sync_status === "pending" ? "syncing…" : "no preview"}
              </div>
            )}
            <div className="space-y-2 p-3">
              <div className="flex items-center justify-between">
                <span className="font-medium">{t.name}</span>
                {t.sync_status === "synced" && (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">✓ synced</span>
                )}
                {t.sync_status === "pending" && (
                  <span className="rounded-full bg-neutral-200 px-2 py-0.5 text-xs">syncing…</span>
                )}
                {t.sync_status === "failed" && (
                  <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-800">failed</span>
                )}
              </div>
              {zoneKeys(t).length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {zoneKeys(t).map((z) => (
                    <span key={z} className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] text-sky-800">#{z}</span>
                  ))}
                </div>
              )}
              {t.sync_error && (
                <p className="text-xs text-amber-700">{t.sync_error}</p>
              )}
              <div className="flex gap-2 pt-1">
                <button onClick={() => resync(t.id)} className="flex-1 rounded-md border px-2 py-1.5 text-xs hover:bg-neutral-50">
                  Re-sync
                </button>
                <button onClick={() => remove(t.id)} className="rounded-md border border-red-200 px-2 py-1.5 text-xs text-red-600 hover:bg-red-50">
                  Delete
                </button>
              </div>
            </div>
          </article>
        ))}
      </section>

      {list.length === 0 && (
        <p className="mt-10 text-center text-neutral-500">
          No templates yet — design a board in Penpot and register it above.
        </p>
      )}
    </main>
  );
}
