"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Experiment = {
  id: string;
  goal: string;
  goal_metric: string;
  status: string;
  budget_total: number;
  budget_spent: number;
  budget_committed: number;
  updated_at: string;
};

type Learning = {
  id: string;
  dimension: string;
  statement: string;
  confidence: number;
  times_applied: number;
};

type Creative = { id: string; human_status: string; governance_status: string; media_type?: string };

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 0 });

export default function Dashboard() {
  const [exps, setExps] = useState<Experiment[]>([]);
  const [learnings, setLearnings] = useState<Learning[]>([]);
  const [creatives, setCreatives] = useState<Creative[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.allSettled([
      apiFetch<Experiment[]>("/experiments").then(setExps),
      apiFetch<Learning[]>("/learnings?limit=6").then(setLearnings),
      apiFetch<Creative[]>("/creatives?status=pending_review").then(setCreatives),
    ]).then((rs) => {
      const bad = rs.find((r) => r.status === "rejected");
      if (bad) setErr((bad as any).reason?.message || null);
    });
  }, []);

  const running = exps.filter((e) => e.status === "running").length;
  const awaiting = exps.filter((e) => e.status === "awaiting_approval").length;
  const spent = exps.reduce((s, e) => s + Number(e.budget_spent || 0), 0);
  const budget = exps.reduce((s, e) => s + Number(e.budget_total || 0), 0);
  const budgetPct = budget > 0 ? Math.min(100, (spent / budget) * 100) : 0;

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-fg">Dashboard</h1>
          <p className="text-sm text-muted mt-0.5">
            The state of every autonomous loop, learning, and creative in one place.
          </p>
        </div>
        <Link href="/experiments" className="btn btn-primary text-sm">
          New experiment →
        </Link>
      </div>

      {err && (
        <div className="chip chip-danger mt-4">{err}</div>
      )}

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-6">
        <Kpi label="Running experiments" value={fmt(running)} accent={running > 0 ? "success" : undefined} />
        <Kpi label="Awaiting approval" value={fmt(awaiting)} accent={awaiting > 0 ? "warn" : undefined} />
        <Kpi label="Budget spent" value={`₹${fmt(spent)}`} sub={budget > 0 ? `of ₹${fmt(budget)} (${budgetPct.toFixed(0)}%)` : "no active budget"} />
        <Kpi label="Learnings on file" value={fmt(learnings.length ? Math.max(learnings.length, 1) : 0)} sub="brand memory" />
      </div>

      {/* Two-up sections */}
      <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Active experiments */}
        <section className="lg:col-span-2 surface p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-fg">Active experiments</h2>
            <Link href="/experiments" className="text-xs text-muted hover:text-fg">See all →</Link>
          </div>

          {exps.length === 0 ? (
            <EmptyState
              title="No experiments yet"
              body="Set a goal and a budget — the loop researches, generates, publishes, measures, and iterates."
              cta={<Link href="/experiments" className="btn btn-primary text-sm mt-3">Start your first experiment</Link>}
            />
          ) : (
            <div className="space-y-2">
              {exps.slice(0, 5).map((e) => {
                const remaining = Number(e.budget_total) - Number(e.budget_spent) - Number(e.budget_committed);
                const pct = Number(e.budget_total) > 0
                  ? (Number(e.budget_spent) / Number(e.budget_total)) * 100 : 0;
                const cpct = Number(e.budget_total) > 0
                  ? (Number(e.budget_committed) / Number(e.budget_total)) * 100 : 0;
                return (
                  <Link
                    key={e.id}
                    href={`/experiments/${e.id}`}
                    className="block surface-2 p-3 hover:border-strong transition"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm text-fg line-clamp-1">{e.goal}</div>
                        <div className="text-[11px] text-subtle mt-0.5">
                          {e.goal_metric} · updated {timeAgo(e.updated_at)}
                        </div>
                      </div>
                      <StatusChip status={e.status} />
                    </div>
                    <div className="mt-2">
                      <div className="gauge">
                        <div className="gauge-fill" style={{ width: `${pct}%` }} />
                        <div className="gauge-committed" style={{ width: `${cpct}%`, left: `${pct}%` }} />
                      </div>
                      <div className="mt-1 text-[10px] text-subtle flex justify-between">
                        <span>₹{fmt(Number(e.budget_spent))} spent</span>
                        <span>₹{fmt(remaining)} left</span>
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </section>

        {/* Recent learnings */}
        <section className="surface p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-fg">Recent learnings</h2>
            <Link href="/learnings" className="text-xs text-muted hover:text-fg">See all →</Link>
          </div>
          {learnings.length === 0 ? (
            <p className="text-xs text-subtle">No learnings distilled yet. They appear after your first analyzed iteration.</p>
          ) : (
            <ul className="space-y-2">
              {learnings.slice(0, 6).map((l) => (
                <li key={l.id} className="text-xs">
                  <div className="flex items-center gap-2">
                    <span className="chip chip-accent">{l.dimension}</span>
                    <span className="text-subtle">{Math.round(l.confidence * 100)}%</span>
                    {l.times_applied > 0 && <span className="text-subtle">· applied ×{l.times_applied}</span>}
                  </div>
                  <div className="text-fg mt-1 line-clamp-2">{l.statement}</div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* Review queue snapshot */}
      <section className="mt-4 surface p-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-fg">Review queue</h2>
          <Link href="/review" className="text-xs text-muted hover:text-fg">Open review →</Link>
        </div>
        {creatives.length === 0 ? (
          <p className="text-xs text-subtle">Nothing pending — you're caught up.</p>
        ) : (
          <p className="text-sm text-muted">
            <span className="text-fg font-medium">{creatives.length}</span> creative
            {creatives.length === 1 ? "" : "s"} awaiting your review
            {creatives.some((c) => c.media_type === "video") ? " (includes video)" : ""}.
          </p>
        )}
      </section>
    </div>
  );
}

// -----------------------------------

function Kpi({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: "success" | "warn" | "danger" }) {
  const accentClass = accent === "success" ? "chip-success" : accent === "warn" ? "chip-warn" : accent === "danger" ? "chip-danger" : "";
  return (
    <div className="surface p-4">
      <div className="text-[11px] uppercase tracking-wider text-subtle">{label}</div>
      <div className="text-2xl text-fg mt-1 font-semibold flex items-baseline gap-2">
        {value}
        {accent && <span className={`chip ${accentClass}`}>live</span>}
      </div>
      {sub && <div className="text-[11px] text-subtle mt-0.5">{sub}</div>}
    </div>
  );
}

function EmptyState({ title, body, cta }: { title: string; body: string; cta?: React.ReactNode }) {
  return (
    <div className="text-center py-8">
      <div className="text-sm text-fg font-medium">{title}</div>
      <div className="text-xs text-muted mt-1 max-w-md mx-auto">{body}</div>
      {cta}
    </div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const map: Record<string, string> = {
    running: "chip-success", paused: "chip-warn",
    awaiting_approval: "chip-warn", goal_met: "chip-accent",
    budget_exhausted: "chip-info", stopped: "chip", failed: "chip-danger", draft: "chip",
  };
  return <span className={`chip ${map[status] || "chip"}`}>{status.replace(/_/g, " ")}</span>;
}

function timeAgo(iso: string): string {
  const d = new Date(iso).getTime();
  const s = Math.max(1, Math.floor((Date.now() - d) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
