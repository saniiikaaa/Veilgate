from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "local"
    governance_port: int = 8080

    database_url: str
    migration_database_url: str = ""

    vault_key_provider: str = "file"
    vault_key_file: str = "./secrets/dev.key"
    vault_key_hex: str = ""

    enable_ner: bool = True
    # Second-opinion LLM pass over already-masked text: off | auto (only when something name-like is left) | always
    llm_judge: str = "auto"
    llm_judge_timeout: float = 15.0

    default_tenant_id: str = "11111111-1111-1111-1111-111111111111"

    # The one toggle: "nebius" (Token Factory, Nemotron) or "local" (the company-hosted OpenAI-compatible model).
    llm_provider: str = "nebius"

    upstream_base_url: str = "https://api.tokenfactory.nebius.com/v1/"
    nebius_api_key: str = ""

    nebius_model_nano: str = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    nebius_model_super: str = "nvidia/nemotron-3-super-120b-a12b"
    nebius_model_ultra: str = "nvidia/Nemotron-3-Ultra-550b-a55b"

    local_llm_base_url: str = "https://ai-gpu-node.tailfa114b.ts.net/api/v1"
    local_llm_model: str = "nvidia/Qwen3.6-35B-A3B-NVFP4"
    local_llm_api_key: str = "none"

    allowed_email_domains: str = "example.com"

    # When set, the five agent hooks require this value in the X-Veilgate-Key header. Empty = open (local development).
    hook_api_key: str = ""
    auth_key_file: str = "./secrets/auth.key"
    auth_key_hex: str = ""
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
