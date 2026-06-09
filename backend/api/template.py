"""Template config — TENANT-WIDE (logo position, title bar, CTA style, CTA colour).

Previously stored per brand_kit; v2.0 moves it onto the tenants table since
template should be consistent across all brands within a tenant.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import CurrentUser, current_user
from db.session import tenant_connection

router = APIRouter(prefix="/template", tags=["template"])

LOGO_POSITIONS = {"top_left", "top_right", "bottom_left", "bottom_right", "center", "none"}
TITLE_BARS = {"auto", "solid_dark", "solid_brand", "gradient", "none"}
TITLE_POSITIONS = {"top", "center", "bottom"}
CTA_STYLES = {"pill", "underline", "square", "none"}


class TemplateConfig(BaseModel):
    logo_position: str = Field("top_right")
    title_bar: str = Field("auto")
    title_position: str = Field("bottom")
    cta_style: str = Field("pill")
    cta_colour: str | None = Field(None)


@router.get("", response_model=TemplateConfig)
def get_template(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            "SELECT template_config FROM tenants WHERE id = %s",
            (str(user.tenant_id),),
        ).fetchone()
    if not row:
        raise HTTPException(404, "tenant not found")
    cfg = row[0] or {}
    return TemplateConfig(**cfg)


@router.post("", response_model=TemplateConfig)
def set_template(cfg: TemplateConfig, user: CurrentUser = Depends(current_user)):
    if cfg.logo_position not in LOGO_POSITIONS: raise HTTPException(400, "invalid logo_position")
    if cfg.title_bar not in TITLE_BARS: raise HTTPException(400, "invalid title_bar")
    if cfg.title_position not in TITLE_POSITIONS: raise HTTPException(400, "invalid title_position")
    if cfg.cta_style not in CTA_STYLES: raise HTTPException(400, "invalid cta_style")
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "UPDATE tenants SET template_config = %s::jsonb WHERE id = %s",
            (json.dumps(cfg.model_dump()), str(user.tenant_id)),
        ).rowcount
    if not n:
        raise HTTPException(404, "tenant not found")
    return cfg
