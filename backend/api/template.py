"""Template config — logo position, title bar, CTA style on the brand kit."""
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


@router.get("", response_model=TemplateConfig)
def get_template(user: CurrentUser = Depends(current_user)):
    with tenant_connection(user.tenant_id) as conn:
        row = conn.execute(
            "SELECT template_config FROM brand_kits WHERE tenant_id = %s ORDER BY created_at DESC LIMIT 1",
            (str(user.tenant_id),),
        ).fetchone()
    if not row:
        raise HTTPException(404, "brand kit not found")
    return TemplateConfig(**row[0])


@router.post("", response_model=TemplateConfig)
def set_template(cfg: TemplateConfig, user: CurrentUser = Depends(current_user)):
    if cfg.logo_position not in LOGO_POSITIONS: raise HTTPException(400, "invalid logo_position")
    if cfg.title_bar not in TITLE_BARS: raise HTTPException(400, "invalid title_bar")
    if cfg.title_position not in TITLE_POSITIONS: raise HTTPException(400, "invalid title_position")
    if cfg.cta_style not in CTA_STYLES: raise HTTPException(400, "invalid cta_style")
    import json
    with tenant_connection(user.tenant_id) as conn:
        n = conn.execute(
            "UPDATE brand_kits SET template_config = %s::jsonb WHERE tenant_id = %s",
            (json.dumps(cfg.model_dump()), str(user.tenant_id)),
        ).rowcount
    if not n:
        raise HTTPException(404, "brand kit not found")
    return cfg
