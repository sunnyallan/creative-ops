"""v4.0 Phase C — Thin, focused Meta Graph API client.

We deliberately DON'T pull in the full facebook-business SDK. That SDK is
1.8 GB of code, drags an incompatible httplib pinning, and covers 200+
resources we don't need. Instead: a ~15-endpoint httpx client mapped to
exactly the calls the orchestrator + social watcher make.

Surfaces:
  OAuth        : exchange_code, exchange_long_lived, list_ad_accounts,
                 list_pages, get_ig_business_account
  Ads          : create_campaign, create_adset, upload_creative_image,
                 create_ad_creative, create_ad, get_insights
  Organic (IG) : create_ig_media_container, publish_ig_media, get_ig_insights
  Pages        : list_page_posts, get_page_post_insights

All calls are token-scoped (user token OR page token — the caller passes
whichever fits). Errors are raised as MetaAPIError with the Meta error
subcode so the adapters can decide retry vs. fail vs. escalate.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from config import settings

log = logging.getLogger("meta_client")


class MetaAPIError(RuntimeError):
    def __init__(self, message: str, code: int | None = None,
                 subcode: int | None = None, fbtrace_id: str | None = None,
                 status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.fbtrace_id = fbtrace_id
        self.status_code = status_code


def _base() -> str:
    return f"https://graph.facebook.com/{settings.meta_api_version}"


def _raise_if_error(resp: httpx.Response) -> dict:
    try:
        body = resp.json()
    except Exception:
        body = {"_raw": resp.text[:500]}
    if resp.status_code >= 400 or (isinstance(body, dict) and body.get("error")):
        err = (body or {}).get("error") or {}
        raise MetaAPIError(
            err.get("message") or f"HTTP {resp.status_code}",
            code=err.get("code"),
            subcode=err.get("error_subcode"),
            fbtrace_id=err.get("fbtrace_id"),
            status_code=resp.status_code,
        )
    return body


def _get(path: str, token: str, params: dict | None = None) -> dict:
    p = dict(params or {})
    p["access_token"] = token
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{_base()}{path}", params=p)
    return _raise_if_error(r)


def _post(path: str, token: str, data: dict | None = None,
          files: dict | None = None) -> dict:
    d = dict(data or {})
    d["access_token"] = token
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{_base()}{path}", data=d, files=files)
    return _raise_if_error(r)


# ============================================================
# OAuth
# ============================================================

def build_oauth_url(state: str, scopes: list[str]) -> str:
    """URL to redirect the user to for Facebook Login."""
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": settings.meta_redirect_uri,
        "state": state,
        "scope": ",".join(scopes),
        "response_type": "code",
    }
    from urllib.parse import urlencode
    return f"https://www.facebook.com/{settings.meta_api_version}/dialog/oauth?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange the OAuth `code` for a short-lived user token."""
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{_base()}/oauth/access_token", params={
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "redirect_uri": settings.meta_redirect_uri,
            "code": code,
        })
    return _raise_if_error(r)  # {access_token, token_type, expires_in}


def exchange_long_lived(short_token: str) -> dict:
    """Trade the short-lived token for a ~60-day long-lived user token."""
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{_base()}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.meta_app_id,
            "client_secret": settings.meta_app_secret,
            "fb_exchange_token": short_token,
        })
    return _raise_if_error(r)  # {access_token, token_type, expires_in}


def get_me(user_token: str) -> dict:
    return _get("/me", user_token, {"fields": "id,name,email"})


def list_ad_accounts(user_token: str) -> list[dict]:
    body = _get("/me/adaccounts", user_token,
                {"fields": "id,name,account_status,currency,account_id",
                 "limit": 100})
    return body.get("data", [])


def list_pages(user_token: str) -> list[dict]:
    """Returns page objects WITH page-scoped access_tokens embedded."""
    body = _get("/me/accounts", user_token,
                {"fields": "id,name,access_token,tasks", "limit": 100})
    return body.get("data", [])


def get_ig_business_account(page_id: str, page_token: str) -> dict | None:
    body = _get(f"/{page_id}", page_token,
                {"fields": "instagram_business_account{id,username}"})
    ig = body.get("instagram_business_account")
    return ig if ig else None


# ============================================================
# Ads — campaign / adset / creative / ad
# ============================================================

def create_campaign(
    ad_account_id: str, user_token: str, name: str,
    objective: str = "OUTCOME_TRAFFIC", status: str = "PAUSED",
    special_ad_categories: list[str] | None = None,
) -> dict:
    return _post(f"/{ad_account_id}/campaigns", user_token, {
        "name": name, "objective": objective, "status": status,
        "special_ad_categories": ",".join(special_ad_categories or []) or "[]",
    })


def create_adset(
    ad_account_id: str, user_token: str, campaign_id: str, name: str,
    daily_budget_minor_units: int,          # e.g. cents / paise
    targeting: dict, promoted_page_id: str,
    optimization_goal: str = "LINK_CLICKS",
    billing_event: str = "IMPRESSIONS",
    status: str = "PAUSED",
) -> dict:
    return _post(f"/{ad_account_id}/adsets", user_token, {
        "name": name, "campaign_id": campaign_id,
        "daily_budget": daily_budget_minor_units,
        "billing_event": billing_event,
        "optimization_goal": optimization_goal,
        "targeting": _to_json(targeting),
        "promoted_object": _to_json({"page_id": promoted_page_id}),
        "status": status,
    })


def upload_creative_image(ad_account_id: str, user_token: str, image_bytes: bytes,
                          filename: str = "creative.webp") -> str:
    """Uploads an image to the ad account and returns its `hash` for reuse."""
    body = _post(
        f"/{ad_account_id}/adimages", user_token,
        files={"filename": (filename, image_bytes, "image/webp")},
    )
    # Response shape: {"images": {"<filename>": {"hash": "..."}}}
    images = (body or {}).get("images") or {}
    if not images:
        raise MetaAPIError("adimages returned no images", status_code=200)
    entry = next(iter(images.values()))
    return entry["hash"]


def create_link_ad_creative(
    ad_account_id: str, user_token: str, page_id: str,
    image_hash: str, headline: str, body: str, cta_type: str,
    link_url: str, ig_user_id: str | None = None, name: str = "creative",
) -> dict:
    object_story_spec = {
        "page_id": page_id,
        "link_data": {
            "image_hash": image_hash,
            "link": link_url,
            "name": headline[:40],
            "message": body[:125],
            "call_to_action": {"type": cta_type or "LEARN_MORE",
                                 "value": {"link": link_url}},
        },
    }
    if ig_user_id:
        object_story_spec["instagram_actor_id"] = ig_user_id
    return _post(f"/{ad_account_id}/adcreatives", user_token, {
        "name": name,
        "object_story_spec": _to_json(object_story_spec),
    })


def create_ad(
    ad_account_id: str, user_token: str, name: str,
    adset_id: str, creative_id: str, status: str = "PAUSED",
) -> dict:
    return _post(f"/{ad_account_id}/ads", user_token, {
        "name": name, "adset_id": adset_id,
        "creative": _to_json({"creative_id": creative_id}),
        "status": status,
    })


def pause_ad(ad_id: str, user_token: str) -> dict:
    return _post(f"/{ad_id}", user_token, {"status": "PAUSED"})


def get_insights(ad_id: str, user_token: str,
                 fields: list[str] | None = None,
                 date_preset: str = "lifetime") -> dict:
    f = fields or ["impressions", "reach", "clicks", "ctr", "cpc", "spend",
                   "actions", "cost_per_action_type", "frequency"]
    body = _get(f"/{ad_id}/insights", user_token,
                {"fields": ",".join(f), "date_preset": date_preset})
    return (body.get("data") or [{}])[0]


# ============================================================
# Instagram organic publishing (used by instagram_organic adapter + watcher)
# ============================================================

def create_ig_media_container(ig_user_id: str, page_token: str,
                              image_url: str, caption: str,
                              is_carousel_item: bool = False) -> dict:
    """Returns {id: creation_id} for a single-image / carousel-item container."""
    data = {"image_url": image_url, "caption": caption[:2200]}
    if is_carousel_item:
        data["is_carousel_item"] = "true"
    return _post(f"/{ig_user_id}/media", page_token, data)


def create_ig_carousel_container(ig_user_id: str, page_token: str,
                                 child_creation_ids: list[str],
                                 caption: str) -> dict:
    return _post(f"/{ig_user_id}/media", page_token, {
        "media_type": "CAROUSEL",
        "children": ",".join(child_creation_ids),
        "caption": caption[:2200],
    })


def publish_ig_media(ig_user_id: str, page_token: str, creation_id: str) -> dict:
    return _post(f"/{ig_user_id}/media_publish", page_token,
                 {"creation_id": creation_id})


def get_ig_insights(media_id: str, page_token: str,
                    metrics: list[str] | None = None) -> dict:
    m = metrics or ["impressions", "reach", "engagement", "saved", "likes",
                    "comments", "shares", "follows"]
    body = _get(f"/{media_id}/insights", page_token,
                {"metric": ",".join(m)})
    out = {}
    for row in body.get("data") or []:
        vals = row.get("values") or []
        if vals:
            out[row["name"]] = vals[-1].get("value")
    return out


# ============================================================
# Page-level (Facebook page posts + insights) — social watcher uses these
# ============================================================

def list_ig_media(ig_user_id: str, page_token: str, limit: int = 25) -> list[dict]:
    body = _get(f"/{ig_user_id}/media", page_token, {
        "fields": "id,caption,media_type,permalink,timestamp,thumbnail_url",
        "limit": limit,
    })
    return body.get("data", [])


def list_page_posts(page_id: str, page_token: str, limit: int = 25) -> list[dict]:
    body = _get(f"/{page_id}/posts", page_token, {
        "fields": "id,message,permalink_url,created_time,attachments",
        "limit": limit,
    })
    return body.get("data", [])


def get_page_post_insights(post_id: str, page_token: str,
                            metrics: list[str] | None = None) -> dict:
    m = metrics or ["post_impressions", "post_reactions_by_type_total",
                    "post_clicks", "post_engaged_users"]
    body = _get(f"/{post_id}/insights", page_token, {"metric": ",".join(m)})
    out = {}
    for row in body.get("data") or []:
        vals = row.get("values") or []
        if vals:
            out[row["name"]] = vals[-1].get("value")
    return out


# ============================================================
# helpers
# ============================================================

def _to_json(obj: Any) -> str:
    import json as _json
    return _json.dumps(obj, separators=(",", ":"))


def with_retry(fn, *args, retries: int = 3, backoff: float = 1.2, **kw):
    """Small exponential-backoff for transient rate limits / 5xx."""
    for i in range(retries):
        try:
            return fn(*args, **kw)
        except MetaAPIError as e:
            transient = (e.status_code and 500 <= e.status_code < 600) \
                or e.code in (1, 2, 4, 17, 32, 613)  # unknown, service, rate limits
            if not transient or i == retries - 1:
                raise
            time.sleep(backoff ** i)
