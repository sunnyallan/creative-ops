"""Supabase Storage helpers — service-role client, tenant-path-prefixed."""
from __future__ import annotations

from supabase import Client, create_client

from config import settings


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


def download_bytes(path: str) -> bytes:
    sb = service_client()
    return sb.storage.from_(settings.supabase_storage_bucket).download(path)
