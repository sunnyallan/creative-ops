"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { supabaseBrowser } from "@/lib/supabase";

type BrandKit = {
  id: string;
  persona_definitions: { name: string; age_range?: string; income_tier?: string; lifestyle?: string }[];
};

type SavedPartner = {
  id: string;
  name: string;
  logo_path: string | null;
  primary_colour: string | null;
  products_or_services: string | null;
};

export default function NewCampaign() {
  const router = useRouter();
  const [goal, setGoal] = useState("");
  const [personas, setPersonas] = useState<string[]>([]);
  const [allPersonas, setAllPersonas] = useState<BrandKit["persona_definitions"]>([]);

  const [headlineMax, setHeadlineMax] = useState(30);
  const [bodyMax, setBodyMax] = useState(50);
  const [ctaMax, setCtaMax] = useState(15);

  const [partnerOn, setPartnerOn] = useState(false);
  const [savedPartners, setSavedPartners] = useState<SavedPartner[]>([]);
  const [partnerMode, setPartnerMode] = useState<"existing" | "new">("new");
  const [pickedPartnerId, setPickedPartnerId] = useState<string>("");

  const [partnerName, setPartnerName] = useState("");
  const [partnerColour, setPartnerColour] = useState("");
  const [partnerProducts, setPartnerProducts] = useState("");
  const [partnerLogoFile, setPartnerLogoFile] = useState<File | null>(null);
  const [existingLogoPath, setExistingLogoPath] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<BrandKit | null>("/brand-kit").then((bk) => {
      if (bk?.persona_definitions) setAllPersonas(bk.persona_definitions);
    }).catch(() => {});
    apiFetch<SavedPartner[]>("/partners").then((ps) => {
      setSavedPartners(ps);
      if (ps.length > 0) setPartnerMode("existing");
    }).catch(() => {});
  }, []);

  function pickPartner(id: string) {
    setPickedPartnerId(id);
    const p = savedPartners.find((x) => x.id === id);
    if (p) {
      setPartnerName(p.name);
      setPartnerColour(p.primary_colour || "");
      setPartnerProducts(p.products_or_services || "");
      setExistingLogoPath(p.logo_path);
      setPartnerLogoFile(null);
    }
  }

  function togglePersona(name: string) {
    setPersonas(personas.includes(name) ? personas.filter((p) => p !== name) : [...personas, name]);
  }

  async function uploadPartnerLogo(): Promise<string | null> {
    if (!partnerLogoFile) return null;
    const sb = supabaseBrowser();
    const { data: { user } } = await sb.auth.getUser();
    if (!user) throw new Error("not signed in");
    const path = `tenants/${user.id}/campaigns/partner-${Date.now()}-${partnerLogoFile.name}`;
    const { error } = await sb.storage.from("tenant-assets").upload(path, partnerLogoFile, { upsert: true });
    if (error) throw error;
    return path;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true); setErr(null);
    try {
      let partner_brand = null;
      if (partnerOn && partnerName) {
        // If user picked an existing partner and didn't re-upload, reuse the existing logo path.
        const newUploadPath = partnerLogoFile ? await uploadPartnerLogo() : null;
        const logo_path = newUploadPath || existingLogoPath;
        partner_brand = {
          name: partnerName,
          logo_path,
          primary_colour: partnerColour || null,
          products_or_services: partnerProducts || null,
        };
      }
      const c = await apiFetch<{ id: string }>("/campaigns", {
        method: "POST",
        body: JSON.stringify({
          goal,
          persona_segments: personas,
          copy_constraints: {
            headline_max_chars: headlineMax,
            body_max_chars: bodyMax,
            cta_max_chars: ctaMax,
          },
          partner_brand,
        }),
      });
      router.push(`/campaigns/${c.id}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-xl px-6 py-12">
      <h1 className="text-3xl font-semibold">New campaign</h1>
      <form onSubmit={submit} className="mt-6 space-y-4">
        <label className="block">
          <span className="text-sm font-medium">Campaign goal</span>
          <textarea required value={goal} onChange={(e) => setGoal(e.target.value)} rows={4}
            placeholder="e.g. Launch summer menu — drive footfall to flagship stores"
            className="mt-1 w-full rounded-md border px-3 py-2" />
        </label>

        <fieldset className="rounded-md border p-3">
          <legend className="px-1 text-sm font-medium">Personas (pick one or more)</legend>
          {allPersonas.length === 0 ? (
            <p className="text-sm text-neutral-600">
              No personas defined yet. <a href="/onboarding" className="text-blue-600">Add some in onboarding</a>.
            </p>
          ) : (
            <div className="space-y-2">
              {allPersonas.map((p) => (
                <label key={p.name} className="flex items-start gap-3 rounded-md border p-2 hover:bg-neutral-50">
                  <input type="checkbox" checked={personas.includes(p.name)}
                    onChange={() => togglePersona(p.name)} className="mt-1" />
                  <div>
                    <div className="font-medium text-sm">{p.name}</div>
                    {(p.age_range || p.income_tier || p.lifestyle) && (
                      <div className="text-xs text-neutral-600">
                        {[p.age_range, p.income_tier, p.lifestyle].filter(Boolean).join(" · ")}
                      </div>
                    )}
                  </div>
                </label>
              ))}
              <p className="text-xs text-neutral-500">
                One creative set is generated per persona × channel. e.g. 2 personas × 2 channels = 4 creatives.
              </p>
            </div>
          )}
        </fieldset>

        <fieldset className="rounded-md border p-3">
          <legend className="px-1 text-sm font-medium">Copy length limits</legend>
          <div className="space-y-3">
            <label className="block">
              <div className="flex justify-between text-sm"><span>Headline</span><span className="text-neutral-500">{headlineMax} chars</span></div>
              <input type="range" min={20} max={120} value={headlineMax}
                onChange={(e) => setHeadlineMax(Number(e.target.value))} className="w-full" />
            </label>
            <label className="block">
              <div className="flex justify-between text-sm"><span>Body</span><span className="text-neutral-500">{bodyMax} chars</span></div>
              <input type="range" min={40} max={300} value={bodyMax}
                onChange={(e) => setBodyMax(Number(e.target.value))} className="w-full" />
            </label>
            <label className="block">
              <div className="flex justify-between text-sm"><span>CTA</span><span className="text-neutral-500">{ctaMax} chars</span></div>
              <input type="range" min={5} max={60} value={ctaMax}
                onChange={(e) => setCtaMax(Number(e.target.value))} className="w-full" />
            </label>
          </div>
        </fieldset>

        <fieldset className="rounded-md border p-3">
          <legend className="px-1 text-sm font-medium">Partnership offer (optional)</legend>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={partnerOn} onChange={(e) => setPartnerOn(e.target.checked)} />
            This is a co-branded partner offer
          </label>
          {partnerOn && (
            <div className="mt-3 space-y-3">
              {savedPartners.length > 0 && (
                <div className="flex gap-2 text-xs">
                  <button type="button"
                    onClick={() => setPartnerMode("existing")}
                    className={`rounded-md px-3 py-1.5 border ${partnerMode === "existing" ? "bg-neutral-900 text-white border-neutral-900" : "bg-white"}`}>
                    Pick saved ({savedPartners.length})
                  </button>
                  <button type="button"
                    onClick={() => { setPartnerMode("new"); setPickedPartnerId(""); setPartnerName(""); setPartnerColour(""); setPartnerProducts(""); setExistingLogoPath(null); }}
                    className={`rounded-md px-3 py-1.5 border ${partnerMode === "new" ? "bg-neutral-900 text-white border-neutral-900" : "bg-white"}`}>
                    Add new
                  </button>
                </div>
              )}

              {partnerMode === "existing" && savedPartners.length > 0 ? (
                <label className="block text-sm">
                  Saved partner
                  <select value={pickedPartnerId} onChange={(e) => pickPartner(e.target.value)}
                    className="mt-1 w-full rounded-md border px-3 py-2">
                    <option value="">— pick one —</option>
                    {savedPartners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                  {pickedPartnerId && (
                    <span className="mt-1 block text-xs text-neutral-500">
                      Using saved data. To override, click Add new instead.
                    </span>
                  )}
                </label>
              ) : (
                <>
                  <label className="block text-sm">
                    Partner brand name
                    <input value={partnerName} onChange={(e) => setPartnerName(e.target.value)}
                      placeholder="e.g. Cleartrip, Nykaa, BookMyShow"
                      className="mt-1 w-full rounded-md border px-3 py-2" />
                  </label>
                  <label className="block text-sm">
                    What does this partner actually sell?
                    <textarea value={partnerProducts} onChange={(e) => setPartnerProducts(e.target.value)}
                      rows={2}
                      placeholder="e.g. flights, hotels, trains, buses (Cleartrip) — comma-separated transactable products"
                      className="mt-1 w-full rounded-md border px-3 py-2" />
                    <span className="mt-1 block text-xs text-neutral-500">
                      This locks the hero image subject to what the partner actually sells.
                      Saved to your partner directory for next time.
                    </span>
                  </label>
                  <label className="block text-sm">
                    Partner logo (PNG/SVG)
                    <input type="file" accept=".png,.svg" onChange={(e) => setPartnerLogoFile(e.target.files?.[0] || null)}
                      className="mt-1 block" />
                    {existingLogoPath && !partnerLogoFile && (
                      <span className="mt-1 block text-xs text-neutral-500">
                        Existing logo will be reused. Upload to replace.
                      </span>
                    )}
                  </label>
                  <label className="block text-sm">
                    Partner primary colour (optional, hex)
                    <input value={partnerColour} onChange={(e) => setPartnerColour(e.target.value)}
                      placeholder="#FF0000"
                      className="mt-1 w-32 rounded-md border px-3 py-2" />
                  </label>
                </>
              )}
            </div>
          )}
        </fieldset>

        <button disabled={submitting || personas.length === 0}
          className="rounded-md bg-neutral-900 px-4 py-2 text-white disabled:opacity-50">
          {submitting ? "Briefing…" : `Generate brief (${personas.length} persona${personas.length === 1 ? "" : "s"})`}
        </button>
        {err && <p className="text-sm text-red-600">{err}</p>}
      </form>
    </main>
  );
}
