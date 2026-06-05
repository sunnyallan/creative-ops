"""Langfuse-traced Gemini client.

Every generate_content call goes through `traced_generate` which records the
prompt, response, latency, model, and usage to Langfuse. Cost dashboards in
Langfuse use these.

Falls back to plain Gemini when Langfuse keys are unset — no-op when disabled.
"""
from __future__ import annotations

import time
from typing import Any

from google import genai
from google.genai import types as genai_types

from config import settings

_lf = None


def _get_langfuse():
    global _lf
    if _lf is not None:
        return _lf
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    from langfuse import Langfuse
    _lf = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    return _lf


def gemini_client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


def traced_generate(
    *,
    model: str,
    contents: Any,
    config: genai_types.GenerateContentConfig | None = None,
    trace_name: str,
    tenant_id: str | None = None,
    campaign_id: str | None = None,
    metadata: dict[str, Any] | None = None,
):
    """Wrap models.generate_content with a Langfuse generation event."""
    lf = _get_langfuse()
    client = gemini_client()
    started = time.time()

    if lf is None:
        return client.models.generate_content(model=model, contents=contents, config=config)

    trace = lf.trace(
        name=trace_name,
        user_id=tenant_id,
        session_id=campaign_id,
        metadata=metadata or {},
    )
    gen = trace.generation(
        name=trace_name,
        model=model,
        input=str(contents)[:8000],
        metadata=metadata or {},
    )
    try:
        resp = client.models.generate_content(model=model, contents=contents, config=config)
        usage = getattr(resp, "usage_metadata", None)
        gen.end(
            output=getattr(resp, "text", str(resp))[:8000],
            usage={
                "input": getattr(usage, "prompt_token_count", 0) or 0,
                "output": getattr(usage, "candidates_token_count", 0) or 0,
                "total": getattr(usage, "total_token_count", 0) or 0,
            } if usage else None,
        )
        return resp
    except Exception as e:
        gen.end(level="ERROR", status_message=str(e))
        raise
    finally:
        # 5s timeout; non-blocking flush in workers
        try:
            lf.flush()
        except Exception:
            pass
