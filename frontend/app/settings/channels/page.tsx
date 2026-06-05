"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Channel = {
  id?: string;
  key: string;
  display_name: string;
  width: number;
  height: number;
  channel_kind: string;
  enabled: boolean;
  builtin?: boolean;
};

const KIND_OPTIONS = ["image", "story", "email"];

export default function ChannelsSettings() {
  const [list, setList] = useState<Channel[]>([]);
  const [draft, setDraft] = useState<Channel>({
    key: "", display_name: "", width: 1080, height: 1080, channel_kind: "image", enabled: true,
  });
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try { setList(await apiFetch<Channel[]>("/channels")); } catch (e: any) { setErr(e.message); }
  }

  useEffect(() => { refresh(); }, []);

  async function save() {
    try {
      await apiFetch("/channels", { method: "POST", body: JSON.stringify(draft) });
      setDraft({ key: "", display_name: "", width: 1080, height: 1080, channel_kind: "image", enabled: true });
      refresh();
    } catch (e: any) { setErr(e.message); }
  }

  async function remove(id: string) {
    if (!confirm("Delete this channel?")) return;
    await apiFetch(`/channels/${id}`, { method: "DELETE" });
    refresh();
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-3xl font-semibold">Channels</h1>
      <p className="mt-1 text-neutral-600">Sizes each campaign generates a creative for. Built-ins are always included unless overridden.</p>

      <section className="mt-6 rounded-md border bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-50 text-left">
            <tr><th className="px-3 py-2">Name</th><th>Key</th><th>Size</th><th>Kind</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {list.map((c, i) => (
              <tr key={i} className="border-t">
                <td className="px-3 py-2">{c.display_name}</td>
                <td className="font-mono text-xs">{c.key}</td>
                <td>{c.width}×{c.height}</td>
                <td>{c.channel_kind}</td>
                <td>{c.builtin ? <span className="text-neutral-500">built-in</span> : c.enabled ? "enabled" : "disabled"}</td>
                <td>{!c.builtin && c.id && <button onClick={() => remove(c.id!)} className="text-red-600 text-xs">remove</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="mt-8 rounded-md border bg-white p-4">
        <h2 className="font-semibold">Add channel</h2>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="text-sm">Display name
            <input value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })}
              className="mt-1 w-full rounded-md border px-2 py-1.5" />
          </label>
          <label className="text-sm">Key (lowercase, _)
            <input value={draft.key} onChange={(e) => setDraft({ ...draft, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })}
              className="mt-1 w-full rounded-md border px-2 py-1.5 font-mono" />
          </label>
          <label className="text-sm">Width
            <input type="number" value={draft.width} onChange={(e) => setDraft({ ...draft, width: Number(e.target.value) })}
              className="mt-1 w-full rounded-md border px-2 py-1.5" />
          </label>
          <label className="text-sm">Height
            <input type="number" value={draft.height} onChange={(e) => setDraft({ ...draft, height: Number(e.target.value) })}
              className="mt-1 w-full rounded-md border px-2 py-1.5" />
          </label>
          <label className="text-sm">Kind
            <select value={draft.channel_kind} onChange={(e) => setDraft({ ...draft, channel_kind: e.target.value })}
              className="mt-1 w-full rounded-md border px-2 py-1.5">
              {KIND_OPTIONS.map((k) => <option key={k}>{k}</option>)}
            </select>
          </label>
          <label className="text-sm flex items-end gap-2">
            <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
            Enabled
          </label>
        </div>
        <button onClick={save} disabled={!draft.key || !draft.display_name}
          className="mt-4 rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50">
          Save channel
        </button>
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      </section>
    </main>
  );
}
