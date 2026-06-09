"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { supabaseBrowser } from "@/lib/supabase";
import { useBrand } from "@/lib/brand-context";

type Persona = {
  name: string;
  age_range?: string;
  income_tier?: string;
  lifestyle?: string;
  preferred_imagery?: string;
};
type LibraryPersona = Persona & { id: string; tags: string[] };

export default function NewBrandWizard() {
  const router = useRouter();
  const { refresh, setActiveBrandId } = useBrand();

  const [step, setStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Step 1 — Basics
  const [name, setName] = useState("");
  const [tone, setTone] = useState("");
  const [values, setValues] = useState("");

  // Step 2 — Visual
  const [primary, setPrimary] = useState("");
  const [secondary, setSecondary] = useState("");
  const [accent, setAccent] = useState("");
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [headingFontFile, setHeadingFontFile] = useState<File | null>(null);
  const [bodyFontFile, setBodyFontFile] = useState<File | null>(null);

  // Step 3 — Personas
  const [personas, setPersonas] = useState<Persona[]>([{ name: "" }]);
  const [library, setLibrary] = useState<LibraryPersona[]>([]);
  const [showLibrary, setShowLibrary] = useState(false);

  // Step 4 — Rules
  const [rulesDo, setRulesDo] = useState("");
  const [rulesDont, setRulesDont] = useState("");
  const [feel, setFeel] = useState("");

  // Step 5 — Reference banners
  const [refFiles, setRefFiles] = useState<File[]>([]);
  const [styleDescription, setStyleDescription] = useState("");

  // Step 6 — Permission
  const [permission, setPermission] = useState(false);

  useEffect(() => {
    if (step === 3 && library.length === 0) {
      apiFetch<LibraryPersona[]>("/personas/library").then(setLibrary).catch(() => {});
    }
  }, [step, library.length]);

  function addFromLibrary(p: LibraryPersona) {
    if (personas.some((x) => x.name === p.name)) return;
    const seeded: Persona = {
      name: p.name,
      age_range: p.age_range,
      income_tier: p.income_tier,
      lifestyle: p.lifestyle,
      preferred_imagery: p.preferred_imagery,
    };
    setPersonas(personas[0]?.name ? [...personas, seeded] : [seeded]);
    setShowLibrary(false);
  }

  async function uploadOne(file: File, folder: string): Promise<string | null> {
    if (!file) return null;
    const sb = supabaseBrowser();
    const { data: { user } } = await sb.auth.getUser();
    if (!user) throw new Error("not signed in");
    const path = `tenants/${user.id}/brand/${folder}/${Date.now()}-${file.name}`;
    const { error } = await sb.storage.from("tenant-assets").upload(path, file, { upsert: true });
    if (error) throw error;
    return path;
  }

  function refsCharRule(): { ok: boolean; reason?: string } {
    const desc = styleDescription.trim();
    if (refFiles.length >= 2) return { ok: true };
    if (desc.length >= 200) return { ok: true };
    return {
      ok: false,
      reason: `Need at least 2 reference images, OR a style description of 200+ characters (currently ${refFiles.length} refs, ${desc.length} chars).`,
    };
  }

  async function submit() {
    if (!permission) { setErr("Permission checkbox required."); return; }
    const ref = refsCharRule();
    if (!ref.ok) { setErr(ref.reason || "Style requirements not met."); setStep(5); return; }

    setSubmitting(true); setErr(null);
    try {
      // Upload assets first
      const logo_path = logoFile ? await uploadOne(logoFile, "logos") : null;
      const heading_font = headingFontFile ? await uploadOne(headingFontFile, "fonts") : null;
      const body_font = bodyFontFile ? await uploadOne(bodyFontFile, "fonts") : null;

      // Create the brand record
      const brand = await apiFetch<{ id: string }>("/brands", {
        method: "POST",
        body: JSON.stringify({
          name,
          tone,
          brand_values: values,
          primary_colour: primary || null,
          secondary_colour: secondary || null,
          accent_colour: accent || null,
          heading_font,
          body_font,
          logo_path,
          persona_definitions: personas.filter((p) => p.name),
          brand_rules_do: rulesDo || null,
          brand_rules_dont: rulesDont || null,
          brand_feel: feel || null,
          style_description: styleDescription || null,
          asset_permission_accepted: true,
        }),
      });

      // Upload reference banners + register them
      for (const f of refFiles) {
        const p = await uploadOne(f, `references/${brand.id}`);
        if (p) {
          await apiFetch(`/brands/${brand.id}/references`, {
            method: "POST",
            body: JSON.stringify({ image_path: p }),
          });
        }
      }

      await refresh();
      setActiveBrandId(brand.id);
      router.push(`/brands/${brand.id}/references`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  const totalSteps = 6;
  const refRule = refsCharRule();

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-3xl font-semibold">New brand</h1>
      <p className="mt-1 text-neutral-600">Step {step} of {totalSteps}</p>

      {step === 1 && (
        <section className="mt-6 space-y-3">
          <label className="block">
            <span className="text-sm font-medium">Brand name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Tone of voice</span>
            <input value={tone} onChange={(e) => setTone(e.target.value)} placeholder="warm, expert, playful…"
              className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Brand values</span>
            <textarea value={values} onChange={(e) => setValues(e.target.value)} rows={3}
              className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
        </section>
      )}

      {step === 2 && (
        <section className="mt-6 space-y-4">
          <ColourField label="Primary colour" value={primary} onChange={setPrimary} />
          <ColourField label="Secondary colour" value={secondary} onChange={setSecondary} />
          <ColourField label="Accent colour (optional)" value={accent} onChange={setAccent} />
          <FileField label="Logo (PNG/SVG)" accept=".png,.svg" onChange={setLogoFile} file={logoFile} />
          <FileField label="Heading font (TTF/OTF, optional)" accept=".ttf,.otf" onChange={setHeadingFontFile} file={headingFontFile} />
          <FileField label="Body font (TTF/OTF, optional)" accept=".ttf,.otf" onChange={setBodyFontFile} file={bodyFontFile} />
        </section>
      )}

      {step === 3 && (
        <section className="mt-6 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Personas</span>
            <button onClick={() => setShowLibrary(!showLibrary)} className="text-sm text-blue-600">
              {showLibrary ? "Hide library" : "Pick from library"}
            </button>
          </div>
          {showLibrary && (
            <div className="rounded-md border bg-neutral-50 p-2 max-h-72 overflow-auto space-y-1">
              {library.map((p) => (
                <button key={p.id} onClick={() => addFromLibrary(p)}
                  className="w-full text-left rounded p-2 hover:bg-white border border-transparent hover:border-neutral-200">
                  <div className="font-medium text-sm">{p.name}</div>
                  <div className="text-xs text-neutral-600">{p.age_range} · {p.income_tier} · {p.lifestyle}</div>
                </button>
              ))}
              {library.length === 0 && <p className="text-sm text-neutral-500 p-2">Loading library…</p>}
            </div>
          )}
          {personas.map((p, i) => (
            <div key={i} className="rounded-md border p-3 space-y-2">
              <input placeholder="Persona name" value={p.name}
                onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                className="w-full rounded-md border px-3 py-2" />
              <input placeholder="Age range" value={p.age_range || ""}
                onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, age_range: e.target.value } : x))}
                className="w-full rounded-md border px-3 py-2" />
              <input placeholder="Income tier" value={p.income_tier || ""}
                onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, income_tier: e.target.value } : x))}
                className="w-full rounded-md border px-3 py-2" />
              <input placeholder="Lifestyle descriptors" value={p.lifestyle || ""}
                onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, lifestyle: e.target.value } : x))}
                className="w-full rounded-md border px-3 py-2" />
              <input placeholder="Preferred imagery" value={p.preferred_imagery || ""}
                onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, preferred_imagery: e.target.value } : x))}
                className="w-full rounded-md border px-3 py-2" />
            </div>
          ))}
          <button onClick={() => setPersonas([...personas, { name: "" }])} className="text-sm text-blue-600">+ add persona</button>
        </section>
      )}

      {step === 4 && (
        <section className="mt-6 space-y-3">
          <p className="text-sm text-neutral-600">
            Brand rules and feel help the AI stay on-brand. The clearer the more useful.
          </p>
          <label className="block">
            <span className="text-sm font-medium">What we CAN do</span>
            <textarea value={rulesDo} onChange={(e) => setRulesDo(e.target.value)} rows={3}
              placeholder="e.g. use warm earth tones, show family scenes, feature plated meals…"
              className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block">
            <span className="text-sm font-medium">What we must AVOID</span>
            <textarea value={rulesDont} onChange={(e) => setRulesDont(e.target.value)} rows={3}
              placeholder="e.g. no children-only imagery, no busy clutter, no neon colours, no AI text in image…"
              className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Overall feel</span>
            <input value={feel} onChange={(e) => setFeel(e.target.value)}
              placeholder="warm minimal, premium DTC, editorial polish…"
              className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
        </section>
      )}

      {step === 5 && (
        <section className="mt-6 space-y-4">
          <div>
            <h2 className="font-semibold">Reference banners</h2>
            <p className="mt-1 text-sm text-neutral-600">
              Upload <b>at least 2 reference banners</b> showing your existing creative style.
              We'll run them through a vision model to extract the style and use it on every future banner.
            </p>
            <p className="mt-1 text-sm text-neutral-600">
              <b>Or</b>, write a <b>200+ character style description</b> below if you don't have reference banners.
            </p>
          </div>

          <label className="block">
            <span className="text-sm font-medium">Reference images (PNG/JPG)</span>
            <input type="file" multiple accept=".png,.jpg,.jpeg,.webp"
              onChange={(e) => setRefFiles(Array.from(e.target.files || []))}
              className="mt-1 block" />
            <p className="mt-1 text-xs text-neutral-500">{refFiles.length} selected</p>
          </label>

          <label className="block">
            <span className="text-sm font-medium">Style description (alternative to images)</span>
            <textarea value={styleDescription} onChange={(e) => setStyleDescription(e.target.value)} rows={6}
              placeholder="Describe your brand's visual style — colour palette with hex codes, typography, composition, mood, lighting, recurring motifs, design language. Be specific enough that a designer who's never seen your brand could replicate it. 200+ characters."
              className="mt-1 w-full rounded-md border px-3 py-2" />
            <p className="mt-1 text-xs text-neutral-500">{styleDescription.trim().length} / 200 characters</p>
          </label>

          <div className={`rounded-md p-3 text-sm ${refRule.ok ? "bg-emerald-50 text-emerald-900" : "bg-amber-50 text-amber-900"}`}>
            {refRule.ok ? "✓ Style requirement met" : refRule.reason}
          </div>
        </section>
      )}

      {step === 6 && (
        <section className="mt-6 space-y-4">
          <p className="text-sm text-neutral-700">
            By saving, you confirm you own or have rights to use every asset uploaded
            (logos, fonts, reference banners). Creative Ops stores them on your behalf.
          </p>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={permission} onChange={(e) => setPermission(e.target.checked)} />
            <span className="text-sm">I confirm I have rights to use these assets.</span>
          </label>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </section>
      )}

      <div className="mt-8 flex justify-between">
        <button onClick={() => setStep(Math.max(1, step - 1))} disabled={step === 1}
          className="rounded-md border px-4 py-2 disabled:opacity-40">Back</button>
        {step < totalSteps ? (
          <button onClick={() => setStep(step + 1)} disabled={step === 1 && !name}
            className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50">Next</button>
        ) : (
          <button onClick={submit} disabled={!permission || submitting}
            className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50">
            {submitting ? "Saving…" : "Create brand"}
          </button>
        )}
      </div>
    </main>
  );
}

function ColourField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <div className="text-sm font-medium">{label}</div>
      <div className="mt-1 flex items-center gap-2">
        <input type="color"
          value={value && value.startsWith("#") ? value : "#000000"}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-12 rounded border" />
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="#RRGGBB"
          className="w-32 rounded-md border px-3 py-2" />
      </div>
    </div>
  );
}

function FileField({ label, accept, onChange, file }: {
  label: string; accept: string; onChange: (f: File | null) => void; file: File | null;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
      <input type="file" accept={accept} onChange={(e) => onChange(e.target.files?.[0] || null)} className="mt-1 block" />
      {file && <span className="mt-1 block text-xs text-neutral-500">{file.name}</span>}
    </label>
  );
}
