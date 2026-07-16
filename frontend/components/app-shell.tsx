"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useBrand } from "@/lib/brand-context";
import { useTheme } from "@/lib/theme";
import { useState } from "react";

type NavItem = { href: string; label: string; icon: React.ReactNode; group: "core" | "ops" | "config" };

const NAV: NavItem[] = [
  { group: "core",   href: "/dashboard",       label: "Dashboard",   icon: <span>◐</span> },
  { group: "core",   href: "/experiments",     label: "Experiments", icon: <span>◇</span> },
  { group: "core",   href: "/campaigns/new",   label: "New campaign",icon: <span>+</span> },
  { group: "core",   href: "/review",          label: "Review",      icon: <span>✓</span> },

  { group: "ops",    href: "/learnings",       label: "Learnings",   icon: <span>✦</span> },

  { group: "config", href: "/brands",          label: "Brands",      icon: <span>◈</span> },
  { group: "config", href: "/settings/templates", label: "Templates",icon: <span>▦</span> },
  { group: "config", href: "/settings/connections", label: "Connections", icon: <span>⚡</span> },
  { group: "config", href: "/settings",        label: "Settings",    icon: <span>⚙</span> },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { brands, activeBrandId, setActiveBrandId, loading } = useBrand();
  const { theme, toggle } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Bare pages
  if (pathname === "/" || pathname === "/login" || pathname?.startsWith("/onboarding")) {
    return <>{children}</>;
  }

  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname === href || pathname?.startsWith(href + "/");
  };

  const NavList = () => (
    <>
      {(["core", "ops", "config"] as const).map((grp) => (
        <div key={grp} className="mb-4">
          <div className="px-3 mb-1 text-[10px] uppercase tracking-wider text-subtle">
            {grp === "core" ? "Workspace" : grp === "ops" ? "Intelligence" : "Setup"}
          </div>
          {NAV.filter((n) => n.group === grp).map((n) => (
            <Link
              key={n.href}
              href={n.href}
              onClick={() => setMobileOpen(false)}
              className={`flex items-center gap-2 px-3 py-1.5 mx-2 rounded-md text-sm transition ${
                isActive(n.href)
                  ? "bg-elev-2 text-fg"
                  : "text-muted hover:text-fg hover:bg-elev-2"
              }`}
            >
              <span className="text-fg-subtle text-[13px] w-4 inline-block">{n.icon}</span>
              <span>{n.label}</span>
            </Link>
          ))}
        </div>
      ))}
    </>
  );

  return (
    <div className="min-h-screen bg-app flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex w-56 shrink-0 flex-col border-r border-app bg-elev-app">
        <div className="px-5 py-4 border-b border-app">
          <Link href="/dashboard" className="font-semibold tracking-tight text-fg">
            Creative Ops
          </Link>
          <div className="text-[10px] text-subtle mt-0.5">Autonomous growth engine</div>
        </div>

        <div className="p-2">
          {loading ? (
            <div className="px-3 py-2 text-xs text-subtle">Loading brands…</div>
          ) : brands.length > 0 ? (
            <select
              value={activeBrandId || ""}
              onChange={(e) => setActiveBrandId(e.target.value || null)}
              className="input text-sm w-full"
            >
              {brands.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          ) : (
            <button
              onClick={() => router.push("/brands/new")}
              className="btn btn-primary w-full text-xs"
            >
              + Create your first brand
            </button>
          )}
        </div>

        <nav className="flex-1 pt-3">
          <NavList />
        </nav>

        <div className="p-3 border-t border-app flex items-center justify-between">
          <button onClick={toggle} className="btn btn-ghost text-xs" title="Toggle theme">
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
          <span className="text-[10px] text-subtle">v4.0</span>
        </div>
      </aside>

      {/* Mobile header + drawer */}
      <div className="lg:hidden fixed inset-x-0 top-0 z-40 flex items-center justify-between border-b border-app bg-elev-app px-4 py-2">
        <button onClick={() => setMobileOpen(!mobileOpen)} className="btn btn-ghost text-lg" aria-label="menu">☰</button>
        <span className="font-semibold text-fg">Creative Ops</span>
        <button onClick={toggle} className="btn btn-ghost text-sm" title="Toggle theme">
          {theme === "dark" ? "☀" : "☾"}
        </button>
      </div>

      {mobileOpen && (
        <div
          onClick={() => setMobileOpen(false)}
          className="lg:hidden fixed inset-0 z-30 bg-black/40 pt-12"
        >
          <div onClick={(e) => e.stopPropagation()} className="bg-elev-app w-64 h-full py-4 border-r border-app">
            <NavList />
          </div>
        </div>
      )}

      <main className="flex-1 min-w-0 lg:pt-0 pt-12">
        {children}
      </main>
    </div>
  );
}
