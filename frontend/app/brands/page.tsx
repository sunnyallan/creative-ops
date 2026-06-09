"use client";
import Link from "next/link";
import { useBrand } from "@/lib/brand-context";

export default function BrandsListPage() {
  const { brands, activeBrandId, setActiveBrandId, loading } = useBrand();

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-semibold">Brands</h1>
          <p className="mt-1 text-neutral-600">
            Each brand has its own setup, personas, and style reference. Partners are shared across all your brands.
          </p>
        </div>
        <Link href="/brands/new" className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white">
          + New brand
        </Link>
      </div>

      {loading ? (
        <p className="mt-8 text-neutral-500">Loading…</p>
      ) : brands.length === 0 ? (
        <div className="mt-8 rounded-lg border bg-white p-8 text-center">
          <p className="text-neutral-600">No brands yet.</p>
          <Link href="/brands/new" className="mt-3 inline-block rounded-md bg-neutral-900 px-4 py-2 text-sm text-white">
            Create your first brand
          </Link>
        </div>
      ) : (
        <ul className="mt-6 space-y-3">
          {brands.map((b) => (
            <li key={b.id} className="rounded-lg border bg-white p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {b.primary_colour && (
                    <span
                      className="block h-6 w-6 rounded-full border"
                      style={{ background: b.primary_colour }}
                      title={b.primary_colour}
                    />
                  )}
                  <div>
                    <div className="flex items-center gap-2">
                      <Link href={`/brands/${b.id}`} className="font-semibold hover:underline">
                        {b.name}
                      </Link>
                      {activeBrandId === b.id && (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">
                          active
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-neutral-600">
                      {(b.tone || "—").slice(0, 80)}
                      {b.persona_definitions?.length ? ` · ${b.persona_definitions.length} personas` : ""}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setActiveBrandId(b.id)}
                    disabled={activeBrandId === b.id}
                    className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-40"
                  >
                    {activeBrandId === b.id ? "Active" : "Make active"}
                  </button>
                  <Link
                    href={`/brands/${b.id}`}
                    className="rounded-md border px-3 py-1.5 text-sm hover:bg-neutral-50"
                  >
                    Edit
                  </Link>
                  <Link
                    href={`/brands/${b.id}/references`}
                    className="rounded-md border px-3 py-1.5 text-sm hover:bg-neutral-50"
                  >
                    References
                  </Link>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
