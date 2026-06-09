"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { apiFetch } from "./api";

export type Brand = {
  id: string;
  name: string;
  tone?: string | null;
  brand_values?: string | null;
  primary_colour?: string | null;
  secondary_colour?: string | null;
  accent_colour?: string | null;
  heading_font?: string | null;
  body_font?: string | null;
  logo_path?: string | null;
  persona_definitions: Array<{
    name: string;
    age_range?: string;
    income_tier?: string;
    lifestyle?: string;
    preferred_imagery?: string;
  }>;
  brand_rules_do?: string | null;
  brand_rules_dont?: string | null;
  brand_feel?: string | null;
  style_description?: string | null;
};

type Ctx = {
  brands: Brand[];
  activeBrandId: string | null;
  activeBrand: Brand | null;
  setActiveBrandId: (id: string | null) => void;
  refresh: () => Promise<void>;
  loading: boolean;
};

const BrandCtx = createContext<Ctx | null>(null);

const STORAGE_KEY = "creative-ops.active-brand-id";

export function BrandProvider({ children }: { children: React.ReactNode }) {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [activeBrandId, setActiveBrandIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    try {
      const list = await apiFetch<Brand[]>("/brands");
      setBrands(list);

      const stored = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
      const stillExists = stored && list.some((b) => b.id === stored);
      if (stillExists) {
        setActiveBrandIdState(stored);
      } else if (list.length > 0) {
        setActiveBrandIdState(list[0].id);
        if (typeof window !== "undefined") localStorage.setItem(STORAGE_KEY, list[0].id);
      } else {
        setActiveBrandIdState(null);
        if (typeof window !== "undefined") localStorage.removeItem(STORAGE_KEY);
      }
    } catch {
      // not signed in or network blip — leave state as-is
    } finally {
      setLoading(false);
    }
  }

  function setActiveBrandId(id: string | null) {
    setActiveBrandIdState(id);
    if (typeof window === "undefined") return;
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  }

  useEffect(() => {
    refresh();
  }, []);

  const activeBrand = brands.find((b) => b.id === activeBrandId) || null;

  return (
    <BrandCtx.Provider value={{ brands, activeBrandId, activeBrand, setActiveBrandId, refresh, loading }}>
      {children}
    </BrandCtx.Provider>
  );
}

export function useBrand() {
  const ctx = useContext(BrandCtx);
  if (!ctx) throw new Error("useBrand must be used inside BrandProvider");
  return ctx;
}
