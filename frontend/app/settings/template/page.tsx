"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Cfg = {
  logo_position: "top_left" | "top_right" | "bottom_left" | "bottom_right" | "center" | "none";
  title_bar: "auto" | "solid_dark" | "solid_brand" | "gradient" | "none";
  title_position: "top" | "center" | "bottom";
  cta_style: "pill" | "underline" | "square" | "none";
  cta_colour?: string | null;
};

const LOGO = ["top_left", "top_right", "bottom_left", "bottom_right", "center", "none"] as const;
const BAR = ["auto", "solid_dark", "solid_brand", "gradient", "none"] as const;
const POS = ["top", "center", "bottom"] as const;
const CTA = ["pill", "underline", "square", "none"] as const;

export default function TemplateSettings() {
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Cfg>("/template").then(setCfg).catch((e) => setErr(e.message));
  }, []);

  async function save() {
    if (!cfg) return;
    try {
      await apiFetch("/template", { method: "POST", body: JSON.stringify(cfg) });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  if (!cfg) return <main className="p-12">Loading…</main>;

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-3xl font-semibold">Template</h1>
      <p className="mt-1 text-neutral-600">How brand assets sit on every generated creative.</p>

      <div className="mt-6 space-y-4">
        <Field label="Logo position" value={cfg.logo_position} options={LOGO}
          onChange={(v) => setCfg({ ...cfg, logo_position: v as Cfg["logo_position"] })} />
        <Field label="Title bar" value={cfg.title_bar} options={BAR}
          onChange={(v) => setCfg({ ...cfg, title_bar: v as Cfg["title_bar"] })} />
        <Field label="Title position" value={cfg.title_position} options={POS}
          onChange={(v) => setCfg({ ...cfg, title_position: v as Cfg["title_position"] })} />
        <Field label="CTA style" value={cfg.cta_style} options={CTA}
          onChange={(v) => setCfg({ ...cfg, cta_style: v as Cfg["cta_style"] })} />

        <div>
          <div className="text-sm font-medium">CTA button colour</div>
          <div className="mt-1 flex items-center gap-2">
            <input type="color"
              value={cfg.cta_colour || "#111111"}
              onChange={(e) => setCfg({ ...cfg, cta_colour: e.target.value })}
              className="h-9 w-12 rounded border" />
            <input type="text"
              value={cfg.cta_colour || ""}
              onChange={(e) => setCfg({ ...cfg, cta_colour: e.target.value || null })}
              placeholder="#111111 (leave blank to use brand primary)"
              className="rounded-md border px-2 py-1.5 text-sm w-72" />
            <button type="button"
              onClick={() => setCfg({ ...cfg, cta_colour: null })}
              className="text-xs text-blue-600">use brand primary</button>
          </div>
        </div>
      </div>

      <button onClick={save} className="mt-6 rounded-md bg-neutral-900 px-4 py-2 text-white">Save template</button>
      {saved && <span className="ml-3 text-sm text-emerald-600">Saved</span>}
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </main>
  );
}

function Field({ label, value, options, onChange }: {
  label: string; value: string; options: readonly string[]; onChange: (v: string) => void;
}) {
  return (
    <div>
      <div className="text-sm font-medium">{label}</div>
      <div className="mt-1 flex flex-wrap gap-2">
        {options.map((o) => (
          <button key={o} onClick={() => onChange(o)}
            className={`rounded-md px-3 py-1.5 text-sm border ${
              value === o ? "bg-neutral-900 text-white border-neutral-900" : "bg-white"
            }`}>
            {o.replace(/_/g, " ")}
          </button>
        ))}
      </div>
    </div>
  );
}
