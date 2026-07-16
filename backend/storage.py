"""Supabase Storage helpers — cached service-role client, tenant-path-prefixed.

Perf notes:
- service_client() is memoised. `create_client()` is expensive (constructs an
  httpx session + auth state) so calling it per operation kills throughput —
  the review page used to spend ~30s here alone.
- signed_urls_batch() uses the batch API so N urls = 1 HTTP roundtrip instead
  of N. Falls back to per-item if the batch endpoint isn't available on the
  installed supabase-py version.
"""
from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from config import settings


@lru_cache(maxsize=1)
def service_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def upload_bytes(path: str, data: bytes, content_type: str = "image/png") -> str:
    """Upload to the configured bucket. Returns the storage path."""
    sb = service_client()
    sb.storage.from_(settings.supabase_storage_bucket).upload(
        path=path,
        file=data,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return path


def signed_url(path: str, expires_in: int = 3600) -> str:
    sb = service_client()
    res = sb.storage.from_(settings.supabase_storage_bucket).create_signed_url(path, expires_in)
    return res["signedURL"]


def signed_urls_batch(paths: list[str], expires_in: int = 3600) -> dict[str, str]:
    """Sign many paths in one HTTP roundtrip. Returns {path: url}.
    Skips empty inputs; on any per-path failure the item is simply omitted."""
    unique = [p for p in dict.fromkeys(paths) if p]
    if not unique:
        return {}
    sb = service_client()
    bucket = sb.storage.from_(settings.supabase_storage_bucket)
    # supabase-py >= 2.5 has create_signed_urls (plural); fall back if not present.
    fn = getattr(bucket, "create_signed_urls", None)
    out: dict[str, str] = {}
    if callable(fn):
        try:
            results = fn(unique, expires_in) or []
            for r in results:
                # Response shape: [{path, signedURL, error}, ...]
                p = r.get("path")
                url = r.get("signedURL") or r.get("signedUrl")
                if p and url:
                    out[p] = url
            return out
        except Exception:
            pass  # fall through to per-item
    for p in unique:
        try:
            out[p] = signed_url(p, expires_in)
        except Exception:
            continue
    return out


def download_bytes(path: str) -> bytes:
    sb = service_client()
    return sb.storage.from_(settings.supabase_storage_bucket).download(path)
