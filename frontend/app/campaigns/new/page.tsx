"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { supabaseBrowser } from "@/lib/supabase";
import { useBrand } from "@/lib/brand-context";

type SavedPartner = {
  id: string;
  name: string;
  logo_path: string | null;
  primary_colour: string | null;
  products_or_services: string | null;
};

export default function NewCampaign() {
  const router = useRouter();
  const { brands, activeBrandId, setActiveBrandId, activeBrand, loading: brandsLoading } = useBrand();

  const [goal, setGoal] = useState("");
  const [personas, setPersonas] = useState<string[]>([]);

  const [productFile, setProductFile] = useState<File | null>(null);

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
    apiFetch<SavedPartner[]>("/partners").then((ps) => {
      setSavedPartners(ps);
      if (ps.length > 0) setPartnerMode("existing");
    }).catch(() => {});
  }, []);

  // Reset personas when the active brand changes
  useEffect(() => { setPersonas([]); }, [activeBrandId]);

  const brandPersonas = activeBrand?.persona_definitions || [];

  function togglePersona(name: string) {
    setPersonas(personas.includes(name) ? personas.filter((p) => p !== name) : [...personas, name]);
  }

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

  async function uploadFile(file: File, folder: string): Promise<string | null> {
    const sb = supabaseBrowser();
    const { data: { user } } = await sb.auth.getUser();
    if (!user) throw new Error("not signed in");
    const path = `tenants/${user.id}/${folder}/${Date.now()}-${file.name}`;
    const { error } = await sb.storage.from("tenant-assets").upload(path, file, { upsert: true });
    if (error) throw error;
    return path;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!activeBrandId) { setErr("Pick a brand first."); return; }
    setSubmitting(true); setErr(null);
    try {
      let partner_brand = null;
      if (partnerOn && partnerName) {
        const newUpload = partnerLogoFile ? await uploadFile(partnerLogoFile, "campaigns") : null;
        partner_brand = {
          name: partnerName,
          logo_path: newUpload || existingLogoPath,
          primary_colour: partnerColour || null,
          products_or_services: partnerProducts || null,
        };
      }

      let product_image_path: string | null = null;
      if (productFile) {
        product_image_path = await uploadFile(productFile, "campaigns/products");
      }

      const c = await apiFetch<{ id: string }>("/campaigns", {
        method: "POST",
        body: JSON.stringify({
          brand_id: activeBrandId,
          goal,
          persona_segments: personas,
          copy_constraints: {
            headline_max_chars: headlineMax,
            body_max_chars: bodyMax,
            cta_max_chars: ctaMax,
          },
          partner_brand,
          product_image_path,
        }),
      });
      router.push(`/campaigns/${c.id}`);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (brandsLoading) {
    return <main className="p-12">Loading…</main>;
  }

  if (brands.length === 0) {
    return (
      <main className="mx-auto max-w-xl px-6 py-12">
        <h1 className="text-3xl font-semibold">New campaign</h1>
        <p className="mt-4 text-neutral-600">
          You need at least one brand before creating a campaign.
        </p>
        <Link href="/brands/new" className="mt-4 inline-block rounded-md bg-neutral-900 px-4 py-2 text-white">
          Create your first brand
        </Link>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-xl px-6 py-12">
      <h1 className="text-3xl font-semibold">New campaign</h1>
      <form onSubmit={submit} className="mt-6 space-y-4">

        <label className="block">
          <span className="text-sm font-medium">Brand</span>
          <select value={activeBrandId || ""} onChange={(e) => setActiveBrandId(e.target.value)}
            className="mt-1 w-full rounded-md border px-3 py-2">
            {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>

        <label className="block">
          <span className="text-sm font-medium">Campaign goal</span>
          <textarea required value={goal} onChange={(e) => setGoal(e.target.value)} rows={4}
            placeholder="e.g. Launch summer menu — drive footfall to flagship stores"
            className="mt-1 w-full rounded-md border px-3 py-2" />
        </label>

        <fieldset className="rounded-md border p-3">
          <legend className="px-1 text-sm font-medium">Personas (pick one or more)</legend>
          {brandPersonas.length === 0 ? (
            <p className="text-sm text-neutral-600">
              No personas defined on this brand. <Link href={`/brands/${activeBrandId}`} className="text-blue-600">Add some</Link>.
            </p>
          ) : (
            <div className="space-y-2">
              {brandPersonas.map((p) => (
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
                One creative set per persona × channel. e.g. 2 personas × 2 channels = 4 creatives.
              </p>
            </div>
          )}
        </fieldset>

        <fieldset className="rounded-md border p-3">
          <legend className="px-1 text-sm font-medium">Hero product image (optional)</legend>
          <p className="text-xs text-neutral-600">
            Upload a product image to use as the hero subject. The AI will place it on the brand background
            without altering its shape — useful for iPhone-style real-product banners.
          </p>
          <input type="file" accept=".png,.jpg,.jpeg,.webp"
            onChange={(e) => setProductFile(e.target.files?.[0] || null)} className="mt-2 block" />
          {productFile && <p className="mt-1 text-xs text-neutral-500">{productFile.name}</p>}
        </fieldset>

        <fieldset className="rounded-md border p-3">
          <legend className="px-1 text-sm font-medium">Copy length limits</legend>
          <div className="space-y-3">
            <Slider label="Headline" v={headlineMax} on={setHeadlineMax} min={20} max={120} />
            <Slider label="Body" v={bodyMax} on={setBodyMax} min={40} max={300} />
            <Slider label="CTA" v={ctaMax} on={setCtaMax} min={5} max={60} />
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
                  <button type="button" onClick={() => setPartnerMode("existing")}
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
                </label>
              ) : (
                <>
                  <label className="block text-sm">
                    Partner name
                    <input value={partnerName} onChange={(e) => setPartnerName(e.target.value)}
                      className="mt-1 w-full rounded-md border px-3 py-2" />
                  </label>
                  <label className="block text-sm">
                    What does this partner sell?
                    <textarea value={partnerProducts} onChange={(e) => setPartnerProducts(e.target.value)} rows={2}
                      className="mt-1 w-full rounded-md border px-3 py-2" />
                  </label>
                  <label className="block text-sm">
                    Partner logo (PNG/SVG)
                    <input type="file" accept=".png,.svg" onChange={(e) => setPartnerLogoFile(e.target.files?.[0] || null)} className="mt-1 block" />
                  </label>
                  <label className="block text-sm">
                    Partner colour
                    <input value={partnerColour} onChange={(e) => setPartnerColour(e.target.value)} placeholder="#FF0000"
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

function Slider({ label, v, on, min, max }: { label: string; v: number; on: (n: number) => void; min: number; max: number }) {
  return (
    <label className="block">
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="text-neutral-500">{v} chars</span>
      </div>
      <input type="range" min={min} max={max} value={v} onChange={(e) => on(Number(e.target.value))} className="w-full" />
    </label>
  );
}
