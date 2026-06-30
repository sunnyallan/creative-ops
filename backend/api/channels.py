"""Per-tenant custom channel sizes."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/channels", tags=["channels"])

# Built-in defaults — surfaced if the tenant has none.
BUILTIN_CHANNELS = [
    {"key": "meta_feed", "display_name": "Meta Feed", "width": 1080, "height": 1080, "channel_kind": "image"},
    {"key": "whatsapp_banner", "display_name": "WhatsApp Banner", "width": 1200, "height": 628, "channel_kind": "image"},
    {"key": "instagram_post", "display_name": "Instagram Post", "width": 1080, "height": 1080, "channel_kind": "image"},
    {"key": "instagram_portrait", "display_name": "Instagram Portrait", "width": 1080, "height": 1350, "channel_kind": "image"},
    {"key": "instagram_story", "display_name": "Instagram Story", "width": 1080, "height": 1920, "channel_kind": "story"},
    {"key": "instagram_carousel_slide", "display_name": "IG Carousel Slide", "width": 1080, "height": 1080, "channel_kind": "image"},
]

# Channel sets keyed by content_type — which channels apply.
CONTENT_TYPE_CHANNELS = {
    "banner": ["meta_feed", "whatsapp_banner"],
    "social_post": ["instagram_post", "instagram_portrait"],
    "social_carousel": ["instagram_carousel_slide"],  # multiplied by slide count
}


class ChannelIn(BaseModel):
    key: str = Field(..., pattern=r"^[a-z0-9_]+$")
    display_name: str
    width: int = Field(..., ge=64, le=4096)
    height: int = Field(..., ge=64, le=4096)
    channel_kind: str = "image"
    enabled: bool = True


class ChannelOut(ChannelIn):
    id: UUID | None = None
    builtin: bool = False


@router.get("", response_model=list[ChannelOut])
def list_channels(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        rows = conn.execute(
            "SELECT id, key, display_name, width, height, channel_kind, enabled FROM channels "
            "WHERE tenant_id = %s ORDER BY display_name",
            (str(user.tenant_id),),
        ).fetchall()
    custom = [
        ChannelOut(
            id=r[0], key=r[1], display_name=r[2], width=r[3], height=r[4],
            channel_kind=r[5], enabled=r[6], builtin=False,
        )
        for r in rows
    ]
    custom_keys = {c.key for c in custom}
    builtins = [
        ChannelOut(**b, builtin=True) for b in BUILTIN_CHANNELS if b["key"] not in custom_keys
    ]
    return builtins + custom


@router.post("", response_model=ChannelOut)
def upsert_channel(payload: ChannelIn, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            """
            insert into channels (tenant_id, key, display_name, width, height, channel_kind, enabled)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (tenant_id, key)
            do update set display_name = excluded.display_name, width = excluded.width,
                          height = excluded.height, channel_kind = excluded.channel_kind,
                          enabled = excluded.enabled
            returning id
            """,
            (
                str(user.tenant_id), payload.key, payload.display_name, payload.width,
                payload.height, payload.channel_kind, payload.enabled,
            ),
        ).fetchone()
    return ChannelOut(id=row[0], builtin=False, **payload.model_dump())


@router.delete("/{channel_id}")
def delete_channel(channel_id: UUID, user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "delete from channels where id = %s and tenant_id = %s",
            (str(channel_id), str(user.tenant_id)),
        ).rowcount
    if not n:
        raise HTTPException(404, "channel not found")
    return {"ok": True}


def active_channels_for(tenant_id: UUID, content_type: str = "banner") -> list[dict]:
    """Briefing agent helper — returns enabled channels for this content_type.

    For 'banner' content: meta_feed + whatsapp_banner + any custom 'image' channels.
    For 'social_post': Instagram square + portrait built-ins.
    For 'social_carousel': single 1080² slide template (multiplied by slide count downstream).
    """
    allowed_keys = set(CONTENT_TYPE_CHANNELS.get(content_type, ["meta_feed", "whatsapp_banner"]))

    with tenant_connection(tenant_id) as conn:
        rows = conn.execute(
            "SELECT key, display_name, width, height, channel_kind FROM channels "
            "WHERE tenant_id = %s AND enabled = true",
            (str(tenant_id),),
        ).fetchall()
    custom = [
        {"key": r[0], "display_name": r[1], "width": r[2], "height": r[3], "channel_kind": r[4]}
        for r in rows
    ]
    custom_keys = {c["key"] for c in custom}

    # For banner content type, also include custom channels even if not in the allowed_keys list
    # — user defined them, they should work for banners too.
    if content_type == "banner":
        merged = [b for b in BUILTIN_CHANNELS if b["key"] in allowed_keys] + custom
    else:
        # For social types, restrict strictly to the matching built-ins.
        merged = [b for b in BUILTIN_CHANNELS if b["key"] in allowed_keys]

    return [
        {"channel": c["key"], "dimensions": f'{c["width"]}x{c["height"]}', "kind": c["channel_kind"]}
        for c in merged
    ]
