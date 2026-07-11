"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useBrand } from "@/lib/brand-context";

export function TopNav() {
  const { brands, activeBrandId, setActiveBrandId, loading } = useBrand();
  const router = useRouter();
  const pathname = usePathname();

  // Hide nav on login + onboarding routes
  if (pathname === "/" || pathname === "/login" || pathname?.startsWith("/onboarding")) {
    return null;
  }

  return (
    <header className="border-b bg-white">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-6 py-3">
        <Link href="/campaigns/new" className="font-semibold tracking-tight">
          Creative Ops
        </Link>

        <div className="ml-2 flex items-center gap-2">
          {loading ? (
            <span className="text-xs text-neutral-400">…</span>
          ) : brands.length > 0 ? (
            <select
              value={activeBrandId || ""}
              onChange={(e) => setActiveBrandId(e.target.value || null)}
              className="rounded-md border bg-white px-2 py-1 text-sm"
            >
              {brands.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          ) : (
            <button
              onClick={() => router.push("/brands/new")}
              className="rounded-md bg-neutral-900 px-2 py-1 text-xs text-white"
            >
              + Create your first brand
            </button>
          )}
        </div>

        <nav className="ml-auto flex items-center gap-1 text-sm">
          <Link href="/campaigns/new" className="rounded-md px-3 py-1.5 hover:bg-neutral-100">
            New campaign
          </Link>
          <Link href="/review" className="rounded-md px-3 py-1.5 hover:bg-neutral-100">
            Review
          </Link>
          <Link href="/brands" className="rounded-md px-3 py-1.5 hover:bg-neutral-100">
            Brands
          </Link>
          <Link href="/settings/templates" className="rounded-md px-3 py-1.5 hover:bg-neutral-100">
            Templates
          </Link>
          <Link href="/settings" className="rounded-md px-3 py-1.5 hover:bg-neutral-100">
            Settings
          </Link>
        </nav>
      </div>
    </header>
  );
}
