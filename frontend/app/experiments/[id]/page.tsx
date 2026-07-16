"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { StatusChip } from "@/app/dashboard/page";

type Iteration = {
  id: string;
  index: number;
  status: string;
  hypothesis: string | null;
  format: string | null;
  channel: string;
  persona: string | null;
  spend_planned: number;
  spend_actual: number;
  campaign_id: string | null;
  metrics: Record<string, any> | null;
  metrics_history: any[] | null;
  verdict: Record<string, any> | null;
  applied_learnings: any[] | null;
  publish_ref: any;
  published_at: string | null;
  measured_at: string | null;
  measure_deadline: string | null;
  error: string | null;
};

type Detail = {
  id: string;
  goal: string;
  goal_metric: string;
  goal_target: number | null;
  budget_total: number;
  budget_spent: number;
  budget_committed: number;
  per_iteration_cap: number | null;
  channels: string[];
  status: string;
  metric_window_hours: number;
  max_iterations: number;
  created_at: string;
  updated_at: string;
  latest_report: any | null;
  iterations: Iteration[];
};

const fmt = (n?: number | null) =>
  n === null || n === undefined ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: 2 });

export default function ExperimentDetail() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function load() {
    try { setD(await apiFetch<Detail>(`/experiments/${id}`)); }
    catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { load(); }, [id]);

  // Poll every 6s while any iteration is in-flight
  useEffect(() => {
    if (!d) return;
    const active = ["running", "awaiting_approval"].includes(d.status)
      || d.iterations.some((it) => ["planning", "generating", "publishing", "measuring"].includes(it.status));
    if (!active) return;
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, [d]);

  async function call(path: string, method = "POST", label = path) {
    setBusy(label); setErr(null);
    try { await apiFetch(`/experiments/${id}${path}`, { method }); await load(); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  }

  if (!d) return <div className="p-8 text-muted">{err || "Loading…"}</div>;

  const remaining = Number(d.budget_total) - Number(d.budget_spent) - Number(d.budget_committed);
  const pct = d.budget_total > 0 ? (d.budget_spent / d.budget_total) * 100 : 0;
  const cpct = d.budget_total > 0 ? (d.budget_committed / d.budget_total) * 100 : 0;
  const cumulativeMetric = d.iterations.reduce(
    (s, it) => s + Number((it.metrics as any)?.[d.goal_metric] || 0), 0,
  );
  const goalPct = d.goal_target ? Math.min(100, (cumulativeMetric / d.goal_target) * 100) : null;
  const awaiting = d.iterations.find((it) => it.status === "awaiting_approval");
  const terminal = ["stopped", "goal_met", "budget_exhausted", "failed"].includes(d.status);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      {/* Header */}
      <Link href="/experiments" className="text-xs text-muted hover:text-fg">← Experiments</Link>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl text-fg font-semibold line-clamp-2">{d.goal}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
            <span>{d.goal_metric}{d.goal_target ? ` → ${fmt(d.goal_target)}` : ""}</span>
            <span>·</span>
            <span>{d.channels.join(", ")}</span>
            <span>·</span>
            <span>window {d.metric_window_hours}h</span>
            <span>·</span>
            <span>max {d.max_iterations} iters</span>
            <StatusChip status={d.status} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => call("/tick", "POST", "tick")}
            disabled={busy === "tick" || terminal}
            className="btn text-sm" title="Advance the loop one node right now (skips the 15-min beat wait)">
            {busy === "tick" ? "…" : "⟳ Advance"}
          </button>
          {d.status === "running" && (
            <button onClick={() => call("/pause")} disabled={!!busy} className="btn text-sm">
              ‖ Pause
            </button>
          )}
          {(d.status === "paused" || d.status === "awaiting_approval") && (
            <button onClick={() => call("/resume")} disabled={!!busy} className="btn text-sm">
              ▶ Resume
            </button>
          )}
          {!terminal && (
            <button onClick={() => confirm("Stop the loop? Cancels in-flight ads and closes the experiment.") && call("/stop")}
              disabled={!!busy} className="btn btn-danger text-sm">
              ■ Stop
            </button>
          )}
        </div>
      </div>

      {err && <div className="chip chip-danger mt-3">{err}</div>}

      {/* Awaiting-approval banner */}
      {awaiting && (
        <div className="mt-4 surface p-4 border-l-4" style={{ borderLeftColor: "var(--warn)" }}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm text-fg font-medium">Iteration #{awaiting.index} needs approval</div>
              <div className="text-xs text-muted mt-1">
                Planned spend <b>₹{fmt(awaiting.spend_planned)}</b> exceeds your per-iteration cap of{" "}
                ₹{fmt(d.per_iteration_cap)}. Approve to publish, or stop the experiment.
              </div>
              {awaiting.hypothesis && (
                <div className="text-xs text-muted mt-2 italic">"{awaiting.hypothesis}"</div>
              )}
            </div>
            <button onClick={() => call("/approve-iteration", "POST", "approve")}
              disabled={busy === "approve"}
              className="btn btn-primary text-sm">
              {busy === "approve" ? "…" : "Approve iteration"}
            </button>
          </div>
        </div>
      )}

      {/* KPI row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
        <Card label="Iterations" value={String(d.iterations.length)} sub={`of ${d.max_iterations} max`} />
        <Card label="Budget spent" value={`₹${fmt(d.budget_spent)}`} sub={`+ ₹${fmt(d.budget_committed)} committed`} />
        <Card label="Remaining" value={`₹${fmt(remaining)}`} sub={`of ₹${fmt(d.budget_total)}`} />
        <Card label={`Cumulative ${d.goal_metric}`}
              value={fmt(cumulativeMetric)}
              sub={d.goal_target ? `${goalPct?.toFixed(0)}% of ${fmt(d.goal_target)}` : "no target set"} />
      </div>

      {/* Budget gauge */}
      <section className="mt-4 surface p-4">
        <div className="flex justify-between text-xs text-muted mb-2">
          <span>Budget</span>
          <span>{pct.toFixed(0)}% spent · {cpct.toFixed(0)}% committed</span>
        </div>
        <div className="gauge">
          <div className="gauge-fill" style={{ width: `${pct}%` }} />
          <div className="gauge-committed" style={{ width: `${cpct}%`, left: `${pct}%` }} />
        </div>
      </section>

      {/* Iterations timeline */}
      <section className="mt-4 surface p-4">
        <h2 className="text-sm font-semibold text-fg mb-3">Iterations</h2>
        {d.iterations.length === 0 ? (
          <div className="text-sm text-subtle">First iteration is being planned…</div>
        ) : (
          <div className="space-y-3">
            {d.iterations.map((it) => <IterationCard key={it.id} it={it} metric={d.goal_metric} />)}
          </div>
        )}
      </section>

      {/* Report */}
      {terminal && d.latest_report && (
        <section className="mt-4 surface p-5">
          <h2 className="text-sm font-semibold text-fg mb-2">Report</h2>
          <div className="text-fg font-medium">{d.latest_report.headline}</div>
          <p className="text-sm text-muted mt-2 whitespace-pre-wrap">{d.latest_report.summary}</p>

          <ReportList title="What worked" items={d.latest_report.what_worked} accent="chip-success" />
          <ReportList title="What did not" items={d.latest_report.what_did_not} accent="chip-warn" />
          <ReportList title="Recommendations for next experiment" items={d.latest_report.recommendations_for_next_experiment} accent="chip-info" />

          {Array.isArray(d.latest_report.top_learnings) && d.latest_report.top_learnings.length > 0 && (
            <div className="mt-4">
              <div className="text-xs uppercase tracking-wider text-subtle mb-2">Top learnings</div>
              <ul className="space-y-2">
                {d.latest_report.top_learnings.slice(0, 8).map((l: any, i: number) => (
                  <li key={i} className="text-xs">
                    <span className="chip chip-accent mr-2">{l.dimension}</span>
                    <span className="text-fg">{l.statement}</span>
                    <span className="text-subtle ml-2">{Math.round((l.confidence || 0) * 100)}%</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

// -----------------------------------------------------------

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="surface p-3">
      <div className="text-[11px] uppercase tracking-wider text-subtle">{label}</div>
      <div className="text-xl text-fg mt-1 font-semibold">{value}</div>
      {sub && <div className="text-[11px] text-subtle mt-0.5">{sub}</div>}
    </div>
  );
}

function IterationCard({ it, metric }: { it: Iteration; metric: string }) {
  const statusColor = ({
    planning: "", generating: "active", publishing: "active",
    published: "active", measuring: "active",
    awaiting_approval: "warn",
    analyzed: it.verdict?.beat_hypothesis ? "success" : "warn",
    skipped: "warn", failed: "danger",
  } as any)[it.status] || "";
  const primary = Number((it.metrics as any)?.[metric] || 0);

  return (
    <div className="surface-2 p-3">
      <div className="flex items-start gap-3">
        <span className={`timeline-dot mt-1 ${statusColor}`} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <span className="text-xs text-subtle">#{it.index}</span>
              <span className="ml-2 text-sm text-fg font-medium">{it.status.replace(/_/g, " ")}</span>
              <span className="ml-2 text-xs text-muted">
                {[it.format, it.channel, it.persona].filter(Boolean).join(" · ")}
              </span>
            </div>
            <div className="text-xs text-muted">
              spend ₹{fmt(it.spend_actual)} / planned ₹{fmt(it.spend_planned)}
            </div>
          </div>

          {it.hypothesis && (
            <p className="text-sm text-muted mt-1 italic">"{it.hypothesis}"</p>
          )}

          {it.applied_learnings && it.applied_learnings.length > 0 && (
            <details className="mt-2 text-xs">
              <summary className="text-subtle cursor-pointer">
                Applied {it.applied_learnings.length} prior learning{it.applied_learnings.length === 1 ? "" : "s"}
              </summary>
              <ul className="mt-1 pl-4 list-disc text-muted">
                {it.applied_learnings.slice(0, 5).map((l: any, i: number) => (
                  <li key={i}>{l.statement}</li>
                ))}
              </ul>
            </details>
          )}

          {it.metrics && (
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
              <span><b className="text-fg">{fmt(primary)}</b> {metric}</span>
              {"impressions" in it.metrics && <span>{fmt(it.metrics.impressions)} imprs</span>}
              {"clicks" in it.metrics && <span>{fmt(it.metrics.clicks)} clicks</span>}
              {"ctr" in it.metrics && <span>CTR {((it.metrics.ctr || 0) * 100).toFixed(2)}%</span>}
              {"engagement" in it.metrics && <span>{fmt(it.metrics.engagement)} engagement</span>}
              {"conversions" in it.metrics && <span>{fmt(it.metrics.conversions)} conv</span>}
            </div>
          )}

          {it.verdict && (
            <div className="mt-2 text-xs">
              <span className={`chip ${it.verdict.beat_hypothesis ? "chip-success" : "chip-warn"} mr-2`}>
                {it.verdict.beat_hypothesis ? "beat hypothesis" : "did not beat"}
              </span>
              <span className="text-muted">{it.verdict.summary}</span>
            </div>
          )}

          {it.error && <div className="chip chip-danger mt-2">{it.error}</div>}
        </div>
      </div>
    </div>
  );
}

function ReportList({ title, items, accent }: { title: string; items?: string[]; accent: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-4">
      <div className="text-xs uppercase tracking-wider text-subtle mb-1">{title}</div>
      <ul className="space-y-1">
        {items.map((s, i) => (
          <li key={i} className="text-sm text-fg flex gap-2">
            <span className={`chip ${accent} shrink-0`}>·</span>
            <span>{s}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
