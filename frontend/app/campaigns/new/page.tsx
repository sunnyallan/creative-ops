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

type LayoutOption = {
  key: string;
  name: string;
  description: string;
  asset_plan: string;
};

type TemplateOption = {
  id: string;
  name: string;
  sync_status: string;
  preview_url: string | null;
};

export default function NewCampaign() {
  const router = useRouter();
  const { brands, activeBrandId, setActiveBrandId, activeBrand, loading: brandsLoading } = useBrand();

  const [goal, setGoal] = useState("");
  const [personas, setPersonas] = useState<string[]>([]);

  // v2.2 — content type + research + carousel
  const [contentType, setContentType] = useState<"banner" | "social_post" | "social_carousel">("banner");
  const [researchTopic, setResearchTopic] = useState("");
  const [carouselSlides, setCarouselSlides] = useState(5);

  // v3.0 — layout style + custom templates
  const [layouts, setLayouts] = useState<LayoutOption[]>([]);
  const [layoutStyle, setLayoutStyle] = useState<string>("auto");
  const [showAllLayouts, setShowAllLayouts] = useState(false);
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);

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
    apiFetch<LayoutOption[]>("/layouts").then(setLayouts).catch(() => {});
    apiFetch<TemplateOption[]>("/templates")
      .then((ts) => setTemplates(ts.filter((t) => t.sync_status === "synced")))
      .catch(() => {});
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
          content_type: contentType,
          research_topic: researchTopic.trim() || null,
          carousel_slide_count: contentType === "social_carousel" ? carouselSlides : 1,
          layout_style: layoutStyle,
          template_id: templateId,
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

      {/* Content type tabs */}
      <div className="mt-5 grid grid-cols-3 gap-2 rounded-md border bg-neutral-50 p-1">
        {([
          { key: "banner", label: "Banner", desc: "Partnership offer" },
          { key: "social_post", label: "Social post", desc: "Single image, native feed" },
          { key: "social_carousel", label: "Carousel", desc: "Connected story, 3-10 slides" },
        ] as const).map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setContentType(t.key)}
            className={`rounded-md px-3 py-2 text-left transition ${
              contentType === t.key
                ? "bg-white shadow-sm ring-1 ring-neutral-900"
                : "hover:bg-white/60"
            }`}
          >
            <div className="text-sm font-semibold">{t.label}</div>
            <div className="text-xs text-neutral-600">{t.desc}</div>
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="mt-6 space-y-4">

        <label className="block">
          <span className="text-sm font-medium">Brand</span>
          <select value={activeBrandId || ""} onChange={(e) => setActiveBrandId(e.target.value)}
            className="mt-1 w-full rounded-md border px-3 py-2">
            {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>

        {/* Research topic — only for social content */}
        {(contentType === "social_post" || contentType === "social_carousel") && (
          <label className="block">
            <span className="text-sm font-medium">Content topic (researched + grounded)</span>
            <textarea
              value={researchTopic}
              onChange={(e) => setResearchTopic(e.target.value)}
              rows={2}
              placeholder="e.g. Best UPI rewards programmes in India 2026 — what makes OneCard different"
              className="mt-1 w-full rounded-md border px-3 py-2"
            />
            <p className="mt-1 text-xs text-neutral-500">
              Gemini will research this topic with Google grounding (~5s) and use the findings to ground the brief in real facts.
              Optional — leave blank to skip research.
            </p>
          </label>
        )}

        {/* Carousel slide count */}
        {contentType === "social_carousel" && (
          <label className="block">
            <div className="flex justify-between text-sm">
              <span className="font-medium">Number of slides</span>
              <span className="text-neutral-500">{carouselSlides}</span>
            </div>
            <input
              type="range" min={3} max={10} value={carouselSlides}
              onChange={(e) => setCarouselSlides(Number(e.target.value))}
              className="w-full"
            />
            <p className="mt-1 text-xs text-neutral-500">
              Slide 1 generates first and anchors the visual style; slides 2-N reference it for coherence.
            </p>
          </label>
        )}

        <label className="block">
          <span className="text-sm font-medium">{
            contentType === "banner" ? "Campaign goal"
              : contentType === "social_post" ? "Post angle / message"
              : "Carousel narrative goal"
          }</span>
          <textarea required value={goal} onChange={(e) => setGoal(e.target.value)} rows={4}
            placeholder={
              contentType === "banner"
                ? "e.g. Launch summer menu — drive footfall to flagship stores"
                : contentType === "social_post"
                ? "e.g. Show how easy it is to convert big purchases to EMIs"
                : "e.g. Educate users on best UPI rewards on OneCard — hook, 3 points, then CTA"
            }
            className="mt-1 w-full rounded-md border px-3 py-2" />
        </label>

        <fieldset className="rounded-md border p-3">
          <legend className="px-1 text-sm font-medium">Design</legend>

          {templates.length > 0 && (
            <div className="mb-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs font-medium text-neutral-600">Your Penpot templates</span>
                {templateId && (
                  <button type="button" onClick={() => setTemplateId(null)} className="text-xs text-blue-600">
                    clear — use a layout instead
                  </button>
                )}
              </div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {templates.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setTemplateId(templateId === t.id ? null : t.id)}
                    className={`w-28 shrink-0 rounded-md border text-left ${
                      templateId === t.id ? "ring-2 ring-neutral-900" : "hover:border-neutral-400"
                    }`}
                  >
                    {t.preview_url ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={t.preview_url} alt="" className="aspect-square w-full rounded-t-md object-contain bg-neutral-100" />
                    ) : (
                      <div className="aspect-square w-full rounded-t-md bg-neutral-100" />
                    )}
                    <div className="truncate px-1.5 py-1 text-[11px] font-medium">{t.name}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className={templateId ? "pointer-events-none opacity-40" : ""}>
          {templateId && (
            <p className="mb-2 text-xs text-neutral-500">Template selected — layout styles don't apply.</p>
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <button
              type="button"
              onClick={() => setLayoutStyle("auto")}
              className={`rounded-md border px-3 py-2 text-left ${
                layoutStyle === "auto" ? "ring-1 ring-neutral-900 bg-white shadow-sm" : "bg-neutral-50 hover:bg-white"
              }`}
            >
              <div className="text-sm font-semibold">✨ Auto</div>
              <div className="text-xs text-neutral-600">AI picks the best layout for this goal</div>
            </button>
            {(showAllLayouts ? layouts : layouts.slice(0, 5)).map((l) => (
              <button
                key={l.key}
                type="button"
                onClick={() => setLayoutStyle(l.key)}
                className={`rounded-md border px-3 py-2 text-left ${
                  layoutStyle === l.key ? "ring-1 ring-neutral-900 bg-white shadow-sm" : "bg-neutral-50 hover:bg-white"
                }`}
              >
                <div className="flex items-center gap-1 text-sm font-semibold">
                  {l.name}
                  {l.asset_plan === "none" && (
                    <span className="rounded-full bg-emerald-100 px-1.5 text-[10px] text-emerald-800">fast</span>
                  )}
                </div>
                <div className="text-xs text-neutral-600 line-clamp-2">{l.description}</div>
              </button>
            ))}
          </div>
          {layouts.length > 5 && (
            <button type="button" onClick={() => setShowAllLayouts(!showAllLayouts)}
              className="mt-2 text-sm text-blue-600">
              {showAllLayouts ? "Show fewer" : `Show all ${layouts.length} styles`}
            </button>
          )}
          </div>
        </fieldset>

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
          {submitting
            ? (researchTopic.trim() && contentType !== "banner" ? "Researching + briefing…" : "Briefing…")
            : contentType === "social_carousel"
            ? `Generate ${carouselSlides}-slide carousel (${personas.length} persona${personas.length === 1 ? "" : "s"})`
            : contentType === "social_post"
            ? `Generate post (${personas.length} persona${personas.length === 1 ? "" : "s"})`
            : `Generate brief (${personas.length} persona${personas.length === 1 ? "" : "s"})`
          }
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
