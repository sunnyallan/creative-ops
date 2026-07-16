"use client";
import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useBrand } from "@/lib/brand-context";

type Learning = {
  id: string;
  brand_id: string | null;
  dimension: string;
  statement: string;
  confidence: number;
  times_applied: number;
  evidence: any;
  last_validated_at: string | null;
  created_at: string;
};

const DIMENSIONS = ["visual_style", "copy_angle", "format", "persona",
                    "channel", "timing", "tags", "audience", "cta"];

export default function LearningsPage() {
  const { activeBrandId } = useBrand();
  const [items, setItems] = useState<Learning[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [dim, setDim] = useState<string>("");
  const [minConf, setMinConf] = useState<number>(0);
  const [q, setQ] = useState<string>("");
  const [scope, setScope] = useState<"brand" | "all">("brand");
  const [selected, setSelected] = useState<Learning | null>(null);

  async function load() {
    const params = new URLSearchParams();
    if (scope === "brand" && activeBrandId) params.set("brand_id", activeBrandId);
    if (dim) params.set("dimension", dim);
    if (minConf > 0) params.set("min_confidence", String(minConf));
    params.set("limit", "200");
    try { setItems(await apiFetch<Learning[]>(`/learnings?${params}`)); }
    catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { load(); }, [activeBrandId, dim, minConf, scope]);

  const filtered = useMemo(() => {
    if (!q) return items;
    const needle = q.toLowerCase();
    return items.filter((l) => l.statement.toLowerCase().includes(needle));
  }, [q, items]);

  async function remove(id: string) {
    if (!confirm("Delete this learning? It stops influencing future briefs.")) return;
    await apiFetch(`/learnings/${id}`, { method: "DELETE" });
    setSelected(null);
    load();
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-fg">Learnings</h1>
          <p className="text-sm text-muted mt-0.5">
            What the platform has learned across every experiment. These are injected as prompt
            priors on every new brief for this brand.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setScope("brand")} className={`btn text-sm ${scope === "brand" ? "btn-primary" : ""}`}>Active brand</button>
          <button onClick={() => setScope("all")} className={`btn text-sm ${scope === "all" ? "btn-primary" : ""}`}>All brands</button>
        </div>
      </div>

      {/* Filters */}
      <div className="mt-4 surface p-3 flex flex-wrap gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search statements…"
          className="input max-w-xs" />
        <select value={dim} onChange={(e) => setDim(e.target.value)} className="input max-w-xs">
          <option value="">All dimensions</option>
          {DIMENSIONS.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <div className="flex items-center gap-2 pl-2">
          <span className="text-xs text-muted">Min confidence</span>
          <input type="range" min={0} max={1} step={0.05}
            value={minConf} onChange={(e) => setMinConf(Number(e.target.value))}
            className="w-32" />
          <span className="text-xs text-muted tabular-nums">{Math.round(minConf * 100)}%</span>
        </div>
      </div>

      {err && <div className="chip chip-danger mt-4">{err}</div>}

      <div className="mt-4 grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* List */}
        <section className={`${selected ? "lg:col-span-3" : "lg:col-span-5"} space-y-2`}>
          {filtered.length === 0 ? (
            <div className="surface p-8 text-center text-muted text-sm">
              No learnings match. Run an experiment to seed the store — every analyzed iteration adds 0–4 learnings.
            </div>
          ) : (
            filtered.map((l) => (
              <button
                key={l.id}
                onClick={() => setSelected(l)}
                className={`w-full text-left surface p-3 hover:border-strong transition ${
                  selected?.id === l.id ? "border-strong" : ""
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="chip chip-accent">{l.dimension}</span>
                      <span className="text-xs text-subtle">{Math.round(l.confidence * 100)}%</span>
                      {l.times_applied > 0 && (
                        <span className="text-xs text-subtle">· applied ×{l.times_applied}</span>
                      )}
                    </div>
                    <p className="text-sm text-fg">{l.statement}</p>
                  </div>
                  <div className="text-[10px] text-subtle whitespace-nowrap">
                    {new Date(l.created_at).toLocaleDateString()}
                  </div>
                </div>
              </button>
            ))
          )}
        </section>

        {/* Drill-down */}
        {selected && (
          <aside className="lg:col-span-2 surface p-4 h-fit lg:sticky lg:top-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <span className="chip chip-accent">{selected.dimension}</span>
                <span className="chip ml-2">{Math.round(selected.confidence * 100)}% confidence</span>
              </div>
              <button onClick={() => setSelected(null)} className="btn btn-ghost text-xs">✕</button>
            </div>
            <p className="text-fg mt-3">{selected.statement}</p>

            <hr className="rule" />

            <div className="text-xs text-subtle uppercase tracking-wider mb-2">Evidence</div>
            {Array.isArray(selected.evidence) && selected.evidence.length > 0 ? (
              <ul className="space-y-2">
                {selected.evidence.slice(0, 8).map((e: any, i: number) => (
                  <li key={i} className="text-xs surface-2 p-2">
                    <div className="flex items-center gap-2">
                      <span className={`chip ${e.direction === "up" ? "chip-success" : e.direction === "down" ? "chip-danger" : ""}`}>
                        {e.direction || "flat"}
                      </span>
                      {e.iteration_id && (
                        <span className="text-subtle">iter {String(e.iteration_id).slice(0, 8)}</span>
                      )}
                    </div>
                    {e.metric && (
                      <pre className="mt-1 text-[10px] text-muted overflow-x-auto">{JSON.stringify(e.metric, null, 0).slice(0, 220)}</pre>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-subtle">No evidence records yet.</p>
            )}

            <hr className="rule" />
            <div className="text-xs text-muted flex justify-between">
              <span>Applied ×{selected.times_applied}</span>
              {selected.last_validated_at && <span>validated {new Date(selected.last_validated_at).toLocaleDateString()}</span>}
            </div>
            <button onClick={() => remove(selected.id)} className="btn btn-danger text-xs w-full mt-3">
              Delete learning
            </button>
          </aside>
        )}
      </div>
    </div>
  );
}
