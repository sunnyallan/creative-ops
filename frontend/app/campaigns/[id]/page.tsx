"use client";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { apiFetch } from "@/lib/api";

type Campaign = { id: string; goal: string; persona_segment: string | null; status: string; brief: any[] | null };
type Creative = { id: string; channel: string; dimensions: string; headline: string | null; image_url: string | null; governance_status: string; human_status: string };

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: campaign } = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => apiFetch<Campaign>(`/campaigns/${id}`),
  });
  const { data: creatives } = useQuery({
    queryKey: ["creatives", id],
    queryFn: () => apiFetch<Creative[]>(`/creatives?campaign_id=${id}`),
    refetchInterval: 4000,
  });

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
          <p className="mt-2 text-neutral-700">{campaign.goal}</p>
          <p className="mt-1 text-sm text-neutral-500">Status: {campaign.status}</p>

          {campaign.brief && (
            <section className="mt-6">
              <h2 className="text-lg font-medium">Brief</h2>
              <pre className="mt-2 overflow-auto rounded-md bg-neutral-100 p-3 text-xs">{JSON.stringify(campaign.brief, null, 2)}</pre>
            </section>
          )}
        </>
      )}

      <section className="mt-8">
        <h2 className="text-lg font-medium">Creatives</h2>
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
      </section>
    </main>
  );
}
