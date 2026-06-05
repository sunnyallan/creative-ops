from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.brand_kit import router as brand_kit_router
from api.campaigns import router as campaigns_router
from api.channels import router as channels_router
from api.creatives import router as creatives_router
from api.partners import router as partners_router
from api.personas import router as personas_router
from api.template import router as template_router
from auth import CurrentUser, current_user

app = FastAPI(title="Creative Ops API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/me")
def me(user: CurrentUser = Depends(current_user)):
    return {"user_id": str(user.user_id), "email": user.email, "tenant_id": str(user.tenant_id)}


app.include_router(brand_kit_router)
app.include_router(campaigns_router)
app.include_router(channels_router)
app.include_router(creatives_router)
app.include_router(partners_router)
app.include_router(personas_router)
app.include_router(template_router)
