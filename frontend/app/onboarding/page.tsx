"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { supabaseBrowser } from "@/lib/supabase";
import { apiFetch } from "@/lib/api";

type Persona = { name: string; age_range?: string; income_tier?: string; lifestyle?: string; preferred_imagery?: string };
type LibraryPersona = Persona & { id: string; tags: string[] };

export default function Onboarding() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [brandName, setBrandName] = useState("");
  const [tone, setTone] = useState("");
  const [values, setValues] = useState("");
  const [colours, setColours] = useState<string[]>(["#000000"]);
  const [logoFiles, setLogoFiles] = useState<File[]>([]);
  const [fontFiles, setFontFiles] = useState<File[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([{ name: "" }]);
  const [library, setLibrary] = useState<LibraryPersona[]>([]);
  const [showLibrary, setShowLibrary] = useState(false);
  const [permission, setPermission] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const sb = supabaseBrowser();
      const { data: { user } } = await sb.auth.getUser();
      if (!user) router.replace("/login");
      else setUserId(user.id);
    })();
  }, [router]);

  useEffect(() => {
    if (step === 3 && library.length === 0) {
      apiFetch<LibraryPersona[]>("/personas/library").then(setLibrary).catch(() => {});
    }
  }, [step, library.length]);

  function addFromLibrary(p: LibraryPersona) {
    const exists = personas.some((x) => x.name === p.name);
    if (exists) return;
    const seeded: Persona = {
      name: p.name, age_range: p.age_range, income_tier: p.income_tier,
      lifestyle: p.lifestyle, preferred_imagery: p.preferred_imagery,
    };
    setPersonas(personas[0]?.name ? [...personas, seeded] : [seeded]);
    setShowLibrary(false);
  }

  async function uploadAssets(): Promise<{ logo_paths: string[]; fonts: string[] }> {
    const sb = supabaseBrowser();
    const bucket = "tenant-assets";
    const logo_paths: string[] = [];
    const fonts: string[] = [];
    for (const f of logoFiles) {
      const path = `tenants/${userId}/brand/logos/${Date.now()}-${f.name}`;
      const { error } = await sb.storage.from(bucket).upload(path, f, { upsert: true });
      if (error) throw error;
      logo_paths.push(path);
    }
    for (const f of fontFiles) {
      const path = `tenants/${userId}/brand/fonts/${Date.now()}-${f.name}`;
      const { error } = await sb.storage.from(bucket).upload(path, f, { upsert: true });
      if (error) throw error;
      fonts.push(path);
    }
    return { logo_paths, fonts };
  }

  async function submit() {
    if (!permission) { setErr("You must confirm asset rights."); return; }
    setSubmitting(true); setErr(null);
    try {
      const { logo_paths, fonts } = await uploadAssets();
      await apiFetch("/brand-kit", {
        method: "POST",
        body: JSON.stringify({
          brand_name: brandName, tone, values, colours, fonts, logo_paths,
          persona_definitions: personas.filter(p => p.name),
          asset_permission_accepted: true,
        }),
      });
      router.push("/campaigns/new");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <h1 className="text-3xl font-semibold">Brand setup</h1>
      <p className="mt-2 text-neutral-600">Step {step} of 4</p>

      {step === 1 && (
        <section className="mt-6 space-y-3">
          <label className="block">
            <span className="text-sm font-medium">Brand name</span>
            <input value={brandName} onChange={(e) => setBrandName(e.target.value)} className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Tone of voice</span>
            <input value={tone} onChange={(e) => setTone(e.target.value)} placeholder="warm, expert, playful…" className="mt-1 w-full rounded-md border px-3 py-2" />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Brand values</span>
            <textarea value={values} onChange={(e) => setValues(e.target.value)} className="mt-1 w-full rounded-md border px-3 py-2" rows={3} />
          </label>
        </section>
      )}

      {step === 2 && (
        <section className="mt-6 space-y-3">
          <div>
            <span className="text-sm font-medium">Brand colours (hex)</span>
            {colours.map((c, i) => (
              <input key={i} value={c} onChange={(e) => setColours(colours.map((x, j) => j === i ? e.target.value : x))} className="mt-1 mr-2 w-32 rounded-md border px-3 py-2" />
            ))}
            <button onClick={() => setColours([...colours, "#ffffff"])} className="ml-2 text-sm text-blue-600">+ add</button>
          </div>
          <label className="block">
            <span className="text-sm font-medium">Logo files (SVG/PNG)</span>
            <input type="file" multiple accept=".svg,.png" onChange={(e) => setLogoFiles(Array.from(e.target.files || []))} className="mt-1 block" />
          </label>
          <label className="block">
            <span className="text-sm font-medium">Font files (TTF/OTF)</span>
            <input type="file" multiple accept=".ttf,.otf" onChange={(e) => setFontFiles(Array.from(e.target.files || []))} className="mt-1 block" />
          </label>
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
              <input placeholder="Persona name" value={p.name} onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} className="w-full rounded-md border px-3 py-2" />
              <input placeholder="Age range" value={p.age_range || ""} onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, age_range: e.target.value } : x))} className="w-full rounded-md border px-3 py-2" />
              <input placeholder="Income tier" value={p.income_tier || ""} onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, income_tier: e.target.value } : x))} className="w-full rounded-md border px-3 py-2" />
              <input placeholder="Lifestyle descriptors" value={p.lifestyle || ""} onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, lifestyle: e.target.value } : x))} className="w-full rounded-md border px-3 py-2" />
              <input placeholder="Preferred imagery" value={p.preferred_imagery || ""} onChange={(e) => setPersonas(personas.map((x, j) => j === i ? { ...x, preferred_imagery: e.target.value } : x))} className="w-full rounded-md border px-3 py-2" />
            </div>
          ))}
          <button onClick={() => setPersonas([...personas, { name: "" }])} className="text-sm text-blue-600">+ add persona</button>
        </section>
      )}

      {step === 4 && (
        <section className="mt-6 space-y-4">
          <p className="text-sm text-neutral-700">
            By submitting, you confirm you own or have rights to use every asset uploaded
            (logos, fonts, imagery). Creative Ops stores these on your behalf.
          </p>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={permission} onChange={(e) => setPermission(e.target.checked)} />
            <span className="text-sm">I confirm I have rights to use these assets.</span>
          </label>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </section>
      )}

      <div className="mt-8 flex justify-between">
        <button onClick={() => setStep(Math.max(1, step - 1))} className="rounded-md border px-4 py-2" disabled={step === 1}>Back</button>
        {step < 4 ? (
          <button onClick={() => setStep(step + 1)} className="rounded-md bg-neutral-900 px-4 py-2 text-white">Next</button>
        ) : (
          <button onClick={submit} disabled={!permission || submitting} className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50">
            {submitting ? "Saving…" : "Finish setup"}
          </button>
        )}
      </div>
    </main>
  );
}
