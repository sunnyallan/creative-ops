from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    fal_key: str = ""
    sightengine_api_user: str = ""
    sightengine_api_secret: str = ""

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_db_url: str = "postgresql://postgres:postgres@postgres:5432/creative_ops"
    supabase_jwt_secret: str = ""
    supabase_storage_bucket: str = "tenant-assets"

    redis_url: str = "redis://redis:6379/0"

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # v3.0 — self-hosted Penpot (design studio for custom templates)
    penpot_base_url: str = ""       # public URL of the penpot-frontend service
    penpot_access_token: str = ""   # personal access token generated in Penpot UI


settings = Settings()
