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

    # v4.0 Phase C — Meta Marketing API integration
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_redirect_uri: str = ""                 # OAuth callback e.g. https://app.example/settings/connections/meta/callback
    meta_api_version: str = "v21.0"
    meta_use_sandbox: bool = False              # set True while awaiting App Review — uses ad-account sandbox mode
    meta_login_config_id: str = ""              # Facebook Login for Business config id; if set, drives OAuth via config_id
    # Fernet key for encrypting stored OAuth tokens at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = ""

    # Base URL of THIS backend (used to build Meta OAuth state + callback URLs)
    api_base_url: str = ""

    # Access control: comma-separated list of emails allowed to sign in.
    # Empty = allow anyone (default for local dev). Set on the API service
    # in prod to lock the app to specific accounts.
    allowed_emails: str = ""


settings = Settings()
