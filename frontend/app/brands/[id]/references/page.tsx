"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { supabaseBrowser } from "@/lib/supabase";

type Ref = {
  id: string;
  image_path: string;
  extracted_style_description: string | null;
  extraction_status: "pending" | "done" | "failed";
  extraction_error: string | null;
};

export default function BrandReferencesPage() {
  const { id } = useParams<{ id: string }>();
  const [refs, setRefs] = useState<Ref[]>([]);
  const [signedUrls, setSignedUrls] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    try {
      const list = await apiFetch<Ref[]>(`/brands/${id}/references`);
      setRefs(list);
      // Resolve signed URLs for each image
      const sb = supabaseBrowser();
      const map: Record<string, string> = {};
      for (const r of list) {
        try {
          const { data } = await sb.storage.from("tenant-assets").createSignedUrl(r.image_path, 3600);
          if (data?.signedUrl) map[r.id] = data.signedUrl;
        } catch {}
      }
      setSignedUrls(map);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  useEffect(() => { load(); }, [id]);

  // Poll while any extractions are pending
  useEffect(() => {
    if (!refs.some((r) => r.extraction_status === "pending")) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [refs]);

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploading(true); setErr(null);
    try {
      const sb = supabaseBrowser();
      const { data: { user } } = await sb.auth.getUser();
      if (!user) throw new Error("not signed in");
      for (const f of Array.from(files)) {
        const path = `tenants/${user.id}/brand/references/${id}/${Date.now()}-${f.name}`;
        const { error } = await sb.storage.from("tenant-assets").upload(path, f, { upsert: true });
        if (error) throw error;
        await apiFetch(`/brands/${id}/references`, {
          method: "POST",
          body: JSON.stringify({ image_path: path }),
        });
      }
      load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setUploading(false);
    }
  }

  async function remove(refId: string) {
    if (!confirm("Remove this reference?")) return;
    await apiFetch(`/brands/${id}/references/${refId}`, { method: "DELETE" });
    load();
  }

  async function regenerate() {
    try {
      await apiFetch(`/brands/${id}/references/regenerate`, { method: "POST" });
      // refresh brand's aggregated style_description happens server-side
      alert("Brand style description re-aggregated from current references.");
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <Link href={`/brands/${id}`} className="text-sm text-blue-600">← Back to brand</Link>
      <div className="mt-2 flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-semibold">Reference banners</h1>
          <p className="mt-1 text-neutral-600">
            Each upload is analysed by a vision model to extract its style. All extractions are merged
            into your brand's master style description.
          </p>
        </div>
        <button onClick={regenerate} className="rounded-md border px-3 py-1.5 text-sm hover:bg-neutral-50">
          Re-aggregate
        </button>
      </div>

      <section className="mt-6 rounded-lg border bg-white p-4">
        <label className="block">
          <span className="text-sm font-medium">Upload more references (PNG/JPG/WEBP)</span>
          <input type="file" multiple accept=".png,.jpg,.jpeg,.webp"
            disabled={uploading}
            onChange={(e) => upload(e.target.files)}
            className="mt-1 block" />
        </label>
        {uploading && <p className="mt-2 text-sm text-neutral-600">Uploading + queueing extractions…</p>}
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
      </section>

      <section className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        {refs.map((r) => (
          <article key={r.id} className="rounded-lg border bg-white overflow-hidden">
            {signedUrls[r.id] ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={signedUrls[r.id]} alt="" className="w-full aspect-video object-cover" />
            ) : (
              <div className="aspect-video bg-neutral-100" />
            )}
            <div className="p-3 space-y-2">
              <div className="flex items-center justify-between text-xs">
                {r.extraction_status === "done" && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800">✓ analysed</span>}
                {r.extraction_status === "pending" && <span className="rounded-full bg-neutral-200 px-2 py-0.5">analysing…</span>}
                {r.extraction_status === "failed" && <span className="rounded-full bg-red-100 px-2 py-0.5 text-red-800">failed</span>}
                <button onClick={() => remove(r.id)} className="text-red-600">remove</button>
              </div>
              {r.extracted_style_description && (
                <details>
                  <summary className="cursor-pointer text-xs text-blue-600">View extracted style</summary>
                  <p className="mt-1 text-xs text-neutral-700 whitespace-pre-wrap">{r.extracted_style_description}</p>
                </details>
              )}
              {r.extraction_error && (
                <p className="text-xs text-red-600">{r.extraction_error}</p>
              )}
            </div>
          </article>
        ))}
      </section>

      {refs.length === 0 && (
        <p className="mt-12 text-center text-neutral-500">No references yet. Upload above to get started.</p>
      )}
    </main>
  );
}
