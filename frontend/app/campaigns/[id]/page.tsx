"use client";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

type Campaign = {
  id: string;
  goal: string;
  persona_segment: string | null;
  status: string;
  brief: any[] | null;
  content_type?: string;
  research_topic?: string | null;
  research_notes?: string | null;
  carousel_slide_count?: number;
};
type Creative = {
  id: string;
  channel: string;
  dimensions: string;
  headline: string | null;
  image_url: string | null;
  governance_status: string;
  human_status: string;
  persona_segment: string | null;
  slide_index?: number;
};

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: campaign } = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => apiFetch<Campaign>(`/campaigns/${id}`),
  });
  const { data: creatives } = useQuery({
    queryKey: ["creatives", id],
    queryFn: () => apiFetch<Creative[]>(`/creatives?campaign_id=${id}`),
    refetchInterval: (query) => {
      const list = (query.state.data as Creative[] | undefined) ?? [];
      if (list.length === 0) return 8000;
      const stillWorking = list.some(
        (c) => c.governance_status === "pending" || !c.image_url
      );
      return stillWorking ? 8000 : false;
    },
    refetchIntervalInBackground: false,
  });

  const isCarousel = campaign?.content_type === "social_carousel";
  const totalSlides = campaign?.carousel_slide_count || 1;

  // Group creatives — by persona for carousels, flat otherwise
  function groupForCarousel(list: Creative[]) {
    const map = new Map<string, Creative[]>();
    for (const c of list) {
      const key = c.persona_segment || "general";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(c);
    }
    // Sort each persona's slides by slide_index
    for (const [, arr] of map) arr.sort((a, b) => (a.slide_index ?? 0) - (b.slide_index ?? 0));
    return Array.from(map.entries());
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex items-center justify-between">
        <Link href="/review" className="text-sm text-blue-600">← Review queue</Link>
        <Link href="/review" className="rounded-md bg-neutral-900 px-3 py-1.5 text-sm text-white">
          Open review queue
        </Link>
      </div>
      <h1 className="mt-2 text-3xl font-semibold">Campaign</h1>
      {campaign && (
        <>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-full bg-neutral-900 px-2 py-0.5 text-xs text-white">
              {campaign.content_type === "social_carousel" ? `Carousel · ${totalSlides} slides`
                : campaign.content_type === "social_post" ? "Social post"
                : "Banner"}
            </span>
            <span className="text-neutral-500">Status: {campaign.status}</span>
          </div>
          <p className="mt-2 text-neutral-700">{campaign.goal}</p>

          {campaign.research_topic && (
            <details className="mt-4 rounded-lg border bg-white p-4">
              <summary className="cursor-pointer">
                <span className="font-medium">Research</span>
                <span className="ml-2 text-sm text-neutral-500">— {campaign.research_topic}</span>
              </summary>
              {campaign.research_notes ? (
                <div className="mt-3 whitespace-pre-wrap text-sm text-neutral-700">
                  {campaign.research_notes}
                </div>
              ) : (
                <p className="mt-3 text-sm text-neutral-500">
                  No research notes — either the research is still running or it was skipped.
                </p>
              )}
            </details>
          )}

          {campaign.brief && (
            <details className="mt-3 rounded-lg border bg-white p-4">
              <summary className="cursor-pointer font-medium">Brief JSON ({campaign.brief.length} items)</summary>
              <pre className="mt-2 overflow-auto rounded-md bg-neutral-100 p-3 text-xs">{JSON.stringify(campaign.brief, null, 2)}</pre>
            </details>
          )}
        </>
      )}

      <section className="mt-8">
        <h2 className="text-lg font-medium">Creatives</h2>

        {isCarousel ? (
          <div className="mt-3 space-y-6">
            {(creatives ? groupForCarousel(creatives) : []).map(([persona, slides]) => (
              <div key={persona}>
                <div className="mb-2 flex items-center gap-2 text-sm">
                  <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs text-indigo-800">
                    👤 {persona}
                  </span>
                  <span className="text-neutral-500">{slides.length} / {totalSlides} slides</span>
                </div>
                <div className="overflow-x-auto">
                  <div className="flex gap-3 pb-2">
                    {Array.from({ length: totalSlides }).map((_, idx) => {
                      const slide = slides.find((s) => (s.slide_index ?? 0) === idx);
                      return (
                        <div key={idx} className="relative w-56 shrink-0 rounded-lg border bg-white overflow-hidden">
                          <div className="absolute left-2 top-2 z-10 rounded-full bg-neutral-900/80 px-2 py-0.5 text-xs text-white">
                            {idx + 1} / {totalSlides}
                          </div>
                          {slide?.image_url ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={slide.image_url} alt="" className="w-full aspect-square object-cover" />
                          ) : (
                            <div className="aspect-square bg-neutral-100 grid place-items-center text-xs text-neutral-400">
                              generating…
                            </div>
                          )}
                          {slide && (
                            <div className="p-2 text-xs">
                              <p className="font-medium line-clamp-1">{slide.headline}</p>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(creatives || []).map((c) => (
              <div key={c.id} className="rounded-lg border bg-white overflow-hidden">
                {c.image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={c.image_url} alt="" className="w-full" />
                ) : (
                  <div className="aspect-square bg-neutral-100 grid place-items-center text-neutral-400">generating…</div>
                )}
                <div className="p-3 text-sm">
                  <div className="flex justify-between">
                    <span>{c.channel}</span>
                    <span className="text-neutral-500">{c.governance_status} / {c.human_status}</span>
                  </div>
                  <p className="mt-1 font-medium">{c.headline}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
