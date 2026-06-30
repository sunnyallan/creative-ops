"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";

type Creative = {
  id: string;
  campaign_id: string;
  channel: string;
  dimensions: string;
  headline: string | null;
  body: string | null;
  cta: string | null;
  image_url: string | null;
  governance_status: string;
  governance_issues: any;
  human_status: string;
  persona_segment: string | null;
  brand_id?: string | null;
  slide_index?: number;
};

// Group creatives into "review items". Carousel slides for the same
// campaign+persona become one item rendered as a strip.
function groupCreatives(items: Creative[]): Array<
  | { kind: "single"; creative: Creative }
  | { kind: "carousel"; key: string; slides: Creative[] }
> {
  const carouselMap = new Map<string, Creative[]>();
  const singles: Creative[] = [];
  for (const c of items) {
    if (c.channel?.startsWith("instagram_carousel_slide")) {
      const key = `${c.campaign_id}::${c.persona_segment || ""}`;
      if (!carouselMap.has(key)) carouselMap.set(key, []);
      carouselMap.get(key)!.push(c);
    } else {
      singles.push(c);
    }
  }
  const carousels = Array.from(carouselMap.entries()).map(([key, slides]) => ({
    kind: "carousel" as const,
    key,
    slides: slides.sort((a, b) => (a.slide_index ?? 0) - (b.slide_index ?? 0)),
  }));
  return [
    ...carousels,
    ...singles.map((c) => ({ kind: "single" as const, creative: c })),
  ];
}

const REJECT_TAGS = ["wrong-tone", "off-brand-colour", "wrong-imagery", "copy-error", "other"];

export default function ReviewPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["creatives", "pending_review"],
    queryFn: () => apiFetch<Creative[]>("/creatives?status=pending_review"),
    refetchInterval: (query) => {
      // Poll while there's anything still being processed; slow down when the queue is settled.
      const list = (query.state.data as Creative[] | undefined) ?? [];
      const stillWorking = list.some(
        (c) => c.governance_status === "pending" || !c.image_url
      );
      return stillWorking ? 8000 : 30000; // 8s when active, 30s when idle
    },
    refetchIntervalInBackground: false,
  });

  const [rejecting, setRejecting] = useState<Creative | null>(null);
  const [reason, setReason] = useState("");
  const [tag, setTag] = useState("other");

  async function approve(id: string) {
    await apiFetch(`/creatives/${id}/approve`, { method: "POST" });
    qc.invalidateQueries({ queryKey: ["creatives"] });
  }

  async function submitReject() {
    if (!rejecting) return;
    await apiFetch(`/creatives/${rejecting.id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason, tag }),
    });
    setRejecting(null); setReason(""); setTag("other");
    qc.invalidateQueries({ queryKey: ["creatives"] });
  }

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-3xl font-semibold">Review queue</h1>
      <p className="mt-1 text-neutral-600">Approve or reject creatives. Approvals go to platform deployers (stubbed for beta).</p>

      {isLoading && <p className="mt-6">Loading…</p>}
      {error && <p className="mt-6 text-red-600">{(error as Error).message}</p>}

      {/* Carousel items first — they span the full width as horizontal strips */}
      <div className="mt-6 space-y-6">
        {(groupCreatives(data || []).filter((i) => i.kind === "carousel") as Array<{ kind: "carousel"; key: string; slides: Creative[] }>).map((item) => (
          <article key={item.key} className="rounded-lg border bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-xs">
              <span className="rounded-full bg-neutral-900 px-2 py-0.5 text-white">carousel</span>
              <span className="text-neutral-500">{item.slides.length} slides</span>
              {item.slides[0]?.persona_segment && (
                <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-indigo-800">
                  👤 {item.slides[0].persona_segment}
                </span>
              )}
            </div>
            <div className="overflow-x-auto">
              <div className="flex gap-3 pb-2">
                {item.slides.map((s, idx) => (
                  <div key={s.id} className="relative w-56 shrink-0 rounded-md border bg-white overflow-hidden">
                    <div className="absolute left-2 top-2 z-10 rounded-full bg-neutral-900/80 px-2 py-0.5 text-xs text-white">
                      {idx + 1} / {item.slides.length}
                    </div>
                    {s.image_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={s.image_url} alt="" className="w-full aspect-square object-cover" />
                    ) : (
                      <div className="aspect-square bg-neutral-100" />
                    )}
                    <div className="p-2 text-xs">
                      <p className="font-medium line-clamp-2">{s.headline}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="mt-3 flex gap-2">
              <button onClick={async () => {
                for (const s of item.slides) await approve(s.id);
              }} className="flex-1 rounded-md bg-emerald-600 px-3 py-1.5 text-sm text-white">
                Approve all slides
              </button>
              <button onClick={() => setRejecting(item.slides[0])} className="flex-1 rounded-md border px-3 py-1.5 text-sm">
                Reject set
              </button>
            </div>
          </article>
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {(data || []).filter((c) => !c.channel?.startsWith("instagram_carousel_slide")).map((c) => (
          <article key={c.id} className="rounded-lg border bg-white shadow-sm overflow-hidden">
            {c.image_url ? (
              <div className="aspect-square bg-neutral-100 flex items-center justify-center overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={c.image_url} alt="" className="max-w-full max-h-full object-contain" />
              </div>
            ) : (
              <div className="aspect-square bg-neutral-200" />
            )}
            <div className="p-3 space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="rounded-full bg-neutral-900 px-2 py-0.5 text-white">{c.channel}</span>
                <span className="text-neutral-500">{c.dimensions}</span>
                {c.persona_segment && (
                  <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-indigo-800">
                    👤 {c.persona_segment}
                  </span>
                )}
                {c.governance_status === "flagged" && (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800">⚠ flagged</span>
                )}
                {c.governance_status === "passed" && (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800">✓ clean</span>
                )}
                {c.governance_status === "pending" && (
                  <span className="rounded-full bg-neutral-200 px-2 py-0.5 text-neutral-700">checking…</span>
                )}
              </div>
              <h3 className="font-medium">{c.headline}</h3>
              <p className="text-sm text-neutral-600 line-clamp-2">{c.body}</p>
              <p className="text-xs uppercase tracking-wide text-neutral-500">CTA: {c.cta}</p>
              {c.governance_status === "flagged" && (() => {
                const issues = Array.isArray(c.governance_issues?.issues)
                  ? c.governance_issues.issues
                  : Array.isArray(c.governance_issues)
                  ? c.governance_issues
                  : null;
                return issues && issues.length > 0 ? (
                  <details className="mt-2 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
                    <summary className="cursor-pointer font-medium">
                      {issues.length} flag{issues.length === 1 ? "" : "s"} — click to expand
                    </summary>
                    <ul className="mt-1 list-disc pl-4 space-y-0.5">
                      {issues.slice(0, 4).map((it: string, i: number) => (
                        <li key={i}>{it}</li>
                      ))}
                    </ul>
                  </details>
                ) : null;
              })()}
              <div className="flex gap-2 pt-2">
                <button onClick={() => approve(c.id)} className="flex-1 rounded-md bg-emerald-600 px-3 py-1.5 text-sm text-white">
                  Approve
                </button>
                <button onClick={() => setRejecting(c)} className="flex-1 rounded-md border px-3 py-1.5 text-sm">
                  Reject
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>

      {data && data.length === 0 && (
        <p className="mt-12 text-center text-neutral-500">Queue is empty.</p>
      )}

      {rejecting && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
            <h2 className="text-lg font-semibold">Reject creative</h2>
            <p className="mt-1 text-sm text-neutral-600">Reason feeds the Intelligence Engine's next briefing.</p>
            <label className="mt-4 block text-sm">
              Tag
              <select value={tag} onChange={(e) => setTag(e.target.value)} className="mt-1 block w-full rounded-md border px-3 py-2">
                {REJECT_TAGS.map((t) => <option key={t}>{t}</option>)}
              </select>
            </label>
            <label className="mt-3 block text-sm">
              Reason
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} className="mt-1 w-full rounded-md border px-3 py-2" />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button onClick={() => setRejecting(null)} className="rounded-md border px-3 py-1.5">Cancel</button>
              <button onClick={submitReject} disabled={!reason} className="rounded-md bg-red-600 px-3 py-1.5 text-white disabled:opacity-50">
                Reject
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
