from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    render: bool = False
    render_git_commit: str = ""
    production: bool = False

    app_name: str = "Bitcoin Investigator"
    app_mode: Literal["demo", "cloud"] = "demo"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"

    falkordb_url: str = ""
    falkordb_host: str = ""
    falkordb_port: int = 6379
    falkordb_username: str = ""
    falkordb_password: str = ""
    falkordb_graph_name: str = "bitcoin_investigator"
    falkordb_ssl: bool = True
    falkordb_query_timeout_ms: int = 4000
    falkordb_socket_timeout_seconds: float = 8.0
    track2_isolated_demo: bool = False
    isolated_demo_identity: str = "track2-isolated-demo"
    isolated_demo_graph_name: str = "vesper_track2_synthetic_test"

    max_trace_paths: int = 20
    max_case_list: int = 50

    ollama_timeout_seconds: float = 90.0

    # Model provider selection. "local" uses the local Ollama daemon below;
    # "cloud" uses Ollama Cloud. Both keep the same read-only analyst contract,
    # so the provider and model can be compared without code changes.
    model_provider: Literal["local", "cloud"] = "local"

    # Local Ollama analyst (unchanged default).
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    # Ollama Cloud analyst. The API key is read from the environment/.env only
    # and is never written to artifacts, logs, or browser JavaScript.
    ollama_cloud_base_url: str = "https://ollama.com"
    ollama_cloud_model: str = "gpt-oss:20b"
    ollama_api_key: str = ""

    @property
    def model_connection(self) -> dict[str, str]:
        """Resolve the active provider's connection without exposing secrets.

        The returned ``api_key`` is only ever passed to the server-side analyst
        client; callers must not persist or log it.
        """
        if self.model_provider == "cloud":
            return {"provider": "cloud", "base_url": self.ollama_cloud_base_url.rstrip("/"),
                    "model": self.ollama_cloud_model, "api_key": self.ollama_api_key.strip()}
        return {"provider": "local", "base_url": self.ollama_base_url.rstrip("/"),
                "model": self.ollama_model, "api_key": ""}

    @property
    def model_configured(self) -> bool:
        """True when the active provider has everything it needs to run."""
        conn = self.model_connection
        if conn["provider"] == "cloud":
            return bool(conn["api_key"])
        return True

    auth_mode: Literal["none", "cognito"] = "none"
    cognito_region: str = ""
    cognito_user_pool_id: str = ""
    cognito_app_client_id: str = ""
    cognito_domain: str = ""
    cognito_callback_url: str = ""
    cognito_scopes: str = "openid email phone"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def cloud_configured(self) -> bool:
        return bool(self.falkordb_url.strip() or (self.falkordb_host.strip() and self.falkordb_password.strip()))

    @property
    def cognito_configured(self) -> bool:
        return all((self.cognito_region.strip(), self.cognito_user_pool_id.strip(),
                    self.cognito_app_client_id.strip(), self.cognito_domain.strip(),
                    self.cognito_callback_url.strip()))

    @property
    def cognito_scope_list(self) -> list[str]:
        allowed = {"openid", "email", "phone", "profile"}
        return [scope for scope in self.cognito_scopes.split() if scope in allowed]

    @property
    def auth_required(self) -> bool:
        return self.production or self.render or self.auth_mode == "cognito" or self.app_host not in {"127.0.0.1", "localhost", "::1"}


def validate_track2_isolated_demo(settings: Settings) -> None:
    """Fail closed unless the Track 2 writable demo is pinned to loopback."""
    if not settings.track2_isolated_demo:
        return
    parsed = urlsplit(settings.falkordb_url.strip())
    if (settings.app_mode != "cloud"
            or settings.app_host not in {"127.0.0.1", "localhost", "::1"}
            or not settings.isolated_demo_identity.strip()
            or settings.falkordb_graph_name != settings.isolated_demo_graph_name
            or parsed.scheme != "redis"
            or parsed.hostname != "127.0.0.1"
            or parsed.port != 6389
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or settings.falkordb_host.strip()):
        raise RuntimeError("Track 2 demo requires the exact loopback FalkorDB URL, isolated graph, identity, and loopback app bind.")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def validate_production(settings: Settings) -> None:
    """Hosting environment markers cannot silently inherit local demo defaults."""
    if not (settings.production or settings.render):
        return
    if settings.app_mode != "cloud" or settings.track2_isolated_demo:
        raise RuntimeError("Production requires APP_MODE=cloud and disables isolated demo mode.")
    if not settings.cloud_configured:
        raise RuntimeError("Production requires FalkorDB credentials.")
    parsed = urlsplit(settings.falkordb_url)
    if settings.falkordb_url:
        if parsed.scheme != "rediss" or parsed.query:
            raise RuntimeError("Production requires a rediss URL without connection-option overrides.")
    elif not settings.falkordb_ssl:
        raise RuntimeError("Production requires certificate-verified FalkorDB TLS.")
    if settings.falkordb_graph_name != "bitcoin_investigator":
        raise RuntimeError("Production graph must be bitcoin_investigator.")
    if not settings.cognito_configured or settings.auth_mode != "cognito":
        raise RuntimeError("Production requires complete Cognito configuration.")
    if not settings.cognito_callback_url.startswith("https://"):
        raise RuntimeError("Production requires an HTTPS Cognito callback.")
    if not settings.cors_origin_list or any(not origin.startswith("https://") for origin in settings.cors_origin_list):
        raise RuntimeError("Production CORS origins must be explicit HTTPS origins.")
