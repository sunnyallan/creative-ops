"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useBrand } from "@/lib/brand-context";
import { StatusChip } from "@/app/dashboard/page";

type Experiment = {
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
  updated_at: string;
};

const METRICS = ["clicks", "ctr", "conversions", "engagement", "reach",
                  "impressions", "followers", "spend"];
const CHANNELS = ["mock_ads", "meta_ads", "instagram_organic", "facebook_organic"];

export default function ExperimentsPage() {
  const [exps, setExps] = useState<Experiment[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  async function load() {
    try { setExps(await apiFetch<Experiment[]>("/experiments")); }
    catch (e: any) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-fg">Experiments</h1>
          <p className="text-sm text-muted mt-0.5">
            Autonomous loops. Set the goal, set the budget, let the system iterate.
          </p>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="btn btn-primary text-sm">
          {showForm ? "Close" : "+ New experiment"}
        </button>
      </div>

      {err && <div className="chip chip-danger mt-4">{err}</div>}

      {showForm && <CreateForm onCreated={() => { setShowForm(false); load(); }} />}

      <section className="mt-6 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {exps.length === 0 && !showForm ? (
          <div className="col-span-full surface p-10 text-center">
            <div className="text-fg font-medium">No experiments yet</div>
            <div className="text-sm text-muted mt-1 max-w-md mx-auto">
              An experiment is a goal + a budget. The loop researches, generates creatives,
              publishes (mock or real Meta), measures, and iterates — automatically —
              until the goal is met or the budget runs out.
            </div>
            <button onClick={() => setShowForm(true)} className="btn btn-primary text-sm mt-4">
              Start your first experiment
            </button>
          </div>
        ) : (
          exps.map((e) => <ExpCard key={e.id} exp={e} />)
        )}
      </section>
    </div>
  );
}

function fmt(n: number) { return n.toLocaleString(undefined, { maximumFractionDigits: 0 }); }

function ExpCard({ exp }: { exp: Experiment }) {
  const pct = exp.budget_total > 0 ? (exp.budget_spent / exp.budget_total) * 100 : 0;
  const cpct = exp.budget_total > 0 ? (exp.budget_committed / exp.budget_total) * 100 : 0;
  return (
    <Link href={`/experiments/${exp.id}`} className="block surface p-4 hover:border-strong transition">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm text-fg line-clamp-2">{exp.goal}</div>
          <div className="text-[11px] text-subtle mt-1">
            {exp.goal_metric}{exp.goal_target ? ` → ${fmt(exp.goal_target)}` : ""}
            {" · "}
            {exp.channels.join(", ")}
          </div>
        </div>
        <StatusChip status={exp.status} />
      </div>
      <div className="mt-3">
        <div className="gauge">
          <div className="gauge-fill" style={{ width: `${pct}%` }} />
          <div className="gauge-committed" style={{ width: `${cpct}%`, left: `${pct}%` }} />
        </div>
        <div className="mt-1 text-[10px] text-subtle flex justify-between">
          <span>₹{fmt(exp.budget_spent)} spent</span>
          <span>of ₹{fmt(exp.budget_total)}</span>
        </div>
      </div>
    </Link>
  );
}

function CreateForm({ onCreated }: { onCreated: () => void }) {
  const { activeBrandId, brands } = useBrand();
  const router = useRouter();
  const [goal, setGoal] = useState("");
  const [goalMetric, setGoalMetric] = useState("clicks");
  const [goalTarget, setGoalTarget] = useState<string>("");
  const [budget, setBudget] = useState("3000");
  const [perIterCap, setPerIterCap] = useState("500");
  const [channels, setChannels] = useState<string[]>(["mock_ads"]);
  const [metricWindow, setMetricWindow] = useState("1");
  const [minSpend, setMinSpend] = useState("50");
  const [maxIter, setMaxIter] = useState("6");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true); setErr(null);
    try {
      const created = await apiFetch<{ id: string }>("/experiments", {
        method: "POST",
        body: JSON.stringify({
          goal, goal_metric: goalMetric,
          goal_target: goalTarget ? Number(goalTarget) : null,
          budget_total: Number(budget),
          per_iteration_cap: perIterCap ? Number(perIterCap) : null,
          channels, brand_id: activeBrandId || null,
          metric_window_hours: Number(metricWindow),
          min_spend_for_verdict: Number(minSpend),
          max_iterations: Number(maxIter),
        }),
      });
      onCreated();
      router.push(`/experiments/${created.id}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-6 surface p-5 space-y-4">
      <div>
        <label className="field">Goal</label>
        <textarea required rows={2} value={goal} onChange={(e) => setGoal(e.target.value)}
          placeholder="e.g. Learn what carousel style Young Professionals click for our launch"
          className="input" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <label className="field">Goal metric</label>
          <select value={goalMetric} onChange={(e) => setGoalMetric(e.target.value)} className="input">
            {METRICS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="field">Goal target (optional)</label>
          <input type="number" value={goalTarget} onChange={(e) => setGoalTarget(e.target.value)}
            placeholder="e.g. 5000" className="input" />
        </div>
        <div>
          <label className="field">Brand</label>
          <div className="input flex items-center text-muted">
            {brands.find((b) => b.id === activeBrandId)?.name || "— pick in top bar"}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <label className="field">Total budget (₹)</label>
          <input required type="number" value={budget} onChange={(e) => setBudget(e.target.value)} className="input" />
        </div>
        <div>
          <label className="field">Per-iteration cap (₹)</label>
          <input type="number" value={perIterCap} onChange={(e) => setPerIterCap(e.target.value)} className="input" />
          <div className="text-[10px] text-subtle mt-1">Above this → one-click human approval</div>
        </div>
        <div>
          <label className="field">Max iterations</label>
          <input required type="number" value={maxIter} onChange={(e) => setMaxIter(e.target.value)} className="input" />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <label className="field">Metric window (hours)</label>
          <input required type="number" value={metricWindow} onChange={(e) => setMetricWindow(e.target.value)} className="input" />
          <div className="text-[10px] text-subtle mt-1">1 for demo · 48 for real Meta ads</div>
        </div>
        <div>
          <label className="field">Min spend for verdict (₹)</label>
          <input required type="number" value={minSpend} onChange={(e) => setMinSpend(e.target.value)} className="input" />
        </div>
        <div>
          <label className="field">Channels</label>
          <div className="flex flex-wrap gap-2 pt-1.5">
            {CHANNELS.map((c) => (
              <label key={c} className="chip cursor-pointer">
                <input type="checkbox" checked={channels.includes(c)}
                  onChange={() => setChannels((s) => s.includes(c) ? s.filter((x) => x !== c) : [...s, c])}
                  className="mr-1" />
                {c}
              </label>
            ))}
          </div>
        </div>
      </div>

      {err && <div className="chip chip-danger">{err}</div>}

      <div className="flex justify-end">
        <button disabled={submitting || !activeBrandId} className="btn btn-primary">
          {submitting ? "Starting…" : "Start experiment"}
        </button>
      </div>
    </form>
  );
}
