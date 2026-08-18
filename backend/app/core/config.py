from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import AnyUrl, BeforeValidator, computed_field
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# from app.core.constants import DEFAULT_DEV_USER_EMAIL


def _normalize_loopback_http_origin(value: str, *, setting_name: str) -> str:
    origin = value.strip().rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            f"{setting_name} must be a loopback HTTP(S) origin without credentials or a path"
        )
    return origin


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    if isinstance(v, list):
        return [str(item) for item in v]  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    if isinstance(v, str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", env_ignore_empty=True, extra="ignore")

    API_STR: str = "/api"
    FRONTEND_HOST: str = "http://localhost:9000"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = True

    BACKEND_CORS_ORIGINS: Annotated[list[AnyUrl] | str, BeforeValidator(parse_cors)] = []

    @computed_field
    @property
    def ALL_CORS_ORIGINS(self) -> list[str]:  # noqa: N802
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    @computed_field
    @property
    def TEAMS_SSO_AUDIENCE_VALUES(self) -> list[str]:  # noqa: N802
        values = [
            value.strip()
            for value in [
                self.TEAMS_SSO_CLIENT_ID,
                self.TEAMS_SSO_RESOURCE,
                *self.TEAMS_SSO_ALLOWED_AUDIENCES.split(","),
            ]
            if value.strip()
        ]
        return list(dict.fromkeys(values))

    PROJECT_NAME: str = "demo-va"
    POSTGRES_SERVER: str = ""
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""
    POSTGRES_POOL_SIZE: int = 5
    POSTGRES_MAX_OVERFLOW: int = 3
    POSTGRES_POOL_TIMEOUT_SECONDS: float = 30.0
    INTERACTIVE_POSTGRES_POOL_SIZE: int = 2
    INTERACTIVE_POSTGRES_MAX_OVERFLOW: int = 0
    INTERACTIVE_POSTGRES_POOL_TIMEOUT_SECONDS: float = 30.0
    DATABASE_OBSERVABILITY_ENABLED: bool = True
    OTEL_POSTGRES_POOL_SIZE: int = 10
    OTEL_POSTGRES_MAX_OVERFLOW: int = 0
    OTEL_POSTGRES_POOL_TIMEOUT_SECONDS: float = 30.0
    # Must be at least the largest HNSW-backed SQL LIMIT (currently 150), otherwise
    # PostgreSQL can prefer a full scan and sort over the HNSW index.
    HNSW_EF_SEARCH: int = 150
    HNSW_ITERATIVE_SCAN: Literal["off", "relaxed_order", "strict_order"] = "strict_order"

    PYTEST_POSTGRES_SERVER: str = ""
    PYTEST_POSTGRES_PORT: int = 5432
    PYTEST_POSTGRES_USER: str = ""
    PYTEST_POSTGRES_PASSWORD: str = ""
    PYTEST_POSTGRES_DB: str = ""

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> MultiHostUrl:  # noqa: N802
        return MultiHostUrl.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    @computed_field
    @property
    def PYTEST_SQLALCHEMY_DATABASE_URI(self) -> MultiHostUrl:  # noqa: N802
        return MultiHostUrl.build(
            scheme="postgresql+psycopg",
            username=self.PYTEST_POSTGRES_USER,
            password=self.PYTEST_POSTGRES_PASSWORD,
            host=self.PYTEST_POSTGRES_SERVER,
            port=self.PYTEST_POSTGRES_PORT,
            path=self.PYTEST_POSTGRES_DB,
        )

    MODELS: str = ""
    "azure/gpt-5.4,azure/gpt-5.4-mini,"
    "azure/gpt-5.3-chat,azure/gpt-5.5,"
    "openrouter/*"

    # Azure OpenAI Resource 1 settings
    AZURE_API_KEY_1: str = ""
    AZURE_API_BASE_1: str = ""
    AZURE_API_VERSION_1: str = "latest"

    # Azure OpenAI Resource 2 settings
    AZURE_API_KEY_2: str = ""
    AZURE_API_BASE_2: str = ""
    AZURE_API_VERSION_2: str = "latest"

    # Model to Azure resource mapping (e.g., "gpt-5.1:2,gpt-4.1:2")
    # Models not listed default to resource 1
    AZURE_MODEL_RESOURCE_MAP: str = ""

    # OpenRouter settings
    OPENROUTER_API_KEY: str = ""

    # LLM Model Settings
    # Model for chatbot responses
    CHATBOT_MODEL: str = "azure/gpt-5.4"
    CHATBOT_MODEL_TEMPERATURE: float = 0.7
    CHATBOT_MODEL_MAX_TOKENS: int = 4096
    CHATBOT_AZURE_SERVICE_TIER: Literal["default", "priority"] = "default"

    # Model for developer investigation chats.
    INVESTIGATION_MODEL: str = "azure/gpt-5.4"
    INVESTIGATION_REASONING_EFFORT: Literal["none", "low", "medium", "high", "xhigh"] = "high"

    # Model for guardrails
    GUARDRAIL_MODEL: str = "azure/gpt-5.4"
    GUARDRAIL_MODEL_TEMPERATURE: float = 0.1
    GUARDRAIL_MODEL_MAX_TOKENS: int = 2048
    GUARDRAIL_AZURE_SERVICE_TIER: Literal["default", "priority"] = "default"

    # Guardrails configuration
    ENABLE_GUARDRAILS: bool = True
    MAX_GUARDRAILS_RETRIES: int = 2
    GUARDRAILS_BLOCKED_MESSAGE: str = (
        "I'm not able to help with that, but Demo University Admissions can help route "
        "your question to the right team."
    )

    # Model for evaluation/judge
    EVALUATION_MODEL: str = "azure/gpt-5.4"
    EVALUATION_MODEL_TEMPERATURE: float = 0.0
    EVALUATION_MODEL_MAX_TOKENS: int = 0

    # Model for summary generation
    SUMMARIZER_MODEL: str = "azure/gpt-5.4-mini"
    SUMMARIZER_MODEL_MAX_TOKENS: int = 1024

    # Model for title and transcript-title generation
    TITLE_MODEL: str = "azure/gpt-5.4-mini"
    TITLE_MODEL_MAX_TOKENS: int = 32

    # Model for post-response grounding source selection
    GROUNDING_MODEL: str = "azure/gpt-5.4"
    GROUNDING_MODEL_MAX_TOKENS: int = 4096
    GROUNDING_REASONING_EFFORT: Literal["none", "low", "medium", "high", "xhigh"] = "medium"
    GROUNDING_AZURE_SERVICE_TIER: Literal["default", "priority"] = "default"

    # HTTP request timeout for LLM calls (seconds)
    LLM_REQUEST_TIMEOUT: float = 5 * 60.0  # 5 minutes
    # Provider model deltas are buffered by default; tool lifecycle events remain live.
    # Enable only as a rollback/A-B switch for PydanticAI's full request_stream() path.
    PROVIDER_MODEL_STREAMING_ENABLED: bool = False
    # Per-process, per-endpoint HTTPX limits. These defaults match HTTPX defaults.
    PROVIDER_HTTP_MAX_CONNECTIONS: int = 100
    PROVIDER_HTTP_MAX_KEEPALIVE_CONNECTIONS: int = 20

    # Scale for synthetic timing replay by stress/* fake models.
    # Stress models are always forbidden when ENVIRONMENT=production.
    STRESS_FAKE_LATENCY_SCALE: float = 0.0
    STRESS_FAKE_TOOLS: bool = False
    STRESS_FAKE_EMBEDDINGS: bool = False
    STRESS_FAKE_EMBEDDING_BLEND: float = 0.05
    STRESS_HTTP_PROVIDERS_ENABLED: bool = False
    STRESS_FAKE_LLM_URL: str = ""
    STRESS_FAKE_EMBEDDING_URL: str = ""
    STRESS_FAKE_PROVIDER_CA_FILE: str = ""
    STRESS_FAKE_LLM_REQUEST_PADDING_BYTES: int = 0
    STRESS_FAKE_LLM_RESPONSE_PADDING_BYTES: int = 0

    USER_REGISTRATION_TOKEN: str | None = None
    ADMIN_REGISTRATION_TOKEN: str | None = None
    DEV_REGISTRATION_TOKEN: str | None = None
    TEAMS_SSO_ENABLED: bool = False
    TEAMS_SSO_TENANT_ID: str = ""
    TEAMS_SSO_CLIENT_ID: str = ""
    TEAMS_SSO_RESOURCE: str = ""
    TEAMS_SSO_ALLOWED_AUDIENCES: str = ""
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours
    ACCESS_TOKEN_COOKIE_NAME: str = "va_access_token"  # noqa: S105
    ACCESS_TOKEN_COOKIE_PATH: str | None = None
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    REFRESH_TOKEN_COOKIE_NAME: str = "va_refresh_token"  # noqa: S105
    REFRESH_TOKEN_COOKIE_PATH: str | None = None
    REFRESH_TOKEN_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"  # noqa: S105
    REFRESH_TOKEN_COOKIE_SECURE: bool | None = None

    SCHEDULER: bool = False
    OTEL_DATABASE_PERSISTENCE_ENABLED: bool = True

    def model_post_init(self, __context: Any, /) -> None:
        if self.PROVIDER_HTTP_MAX_CONNECTIONS <= 0:
            raise ValueError("PROVIDER_HTTP_MAX_CONNECTIONS must be positive")
        if (
            self.PROVIDER_HTTP_MAX_KEEPALIVE_CONNECTIONS < 0
            or self.PROVIDER_HTTP_MAX_KEEPALIVE_CONNECTIONS > self.PROVIDER_HTTP_MAX_CONNECTIONS
        ):
            raise ValueError(
                "PROVIDER_HTTP_MAX_KEEPALIVE_CONNECTIONS must be between zero and "
                "PROVIDER_HTTP_MAX_CONNECTIONS"
            )

        stress_urls = {
            "STRESS_FAKE_LLM_URL": self.STRESS_FAKE_LLM_URL,
            "STRESS_FAKE_EMBEDDING_URL": self.STRESS_FAKE_EMBEDDING_URL,
        }
        padding_values = {
            "STRESS_FAKE_LLM_REQUEST_PADDING_BYTES": self.STRESS_FAKE_LLM_REQUEST_PADDING_BYTES,
            "STRESS_FAKE_LLM_RESPONSE_PADDING_BYTES": self.STRESS_FAKE_LLM_RESPONSE_PADDING_BYTES,
        }
        for setting_name, value in padding_values.items():
            if not 0 <= value <= 1024 * 1024:
                raise ValueError(f"{setting_name} must be between 0 and 1048576")

        stress_http_configured = bool(
            self.STRESS_HTTP_PROVIDERS_ENABLED
            or any(stress_urls.values())
            or self.STRESS_FAKE_PROVIDER_CA_FILE
            or any(padding_values.values())
        )
        if self.ENVIRONMENT == "production" and stress_http_configured:
            raise ValueError("stress HTTP providers are forbidden when ENVIRONMENT=production")
        if stress_http_configured and not self.STRESS_HTTP_PROVIDERS_ENABLED:
            raise ValueError(
                "STRESS_HTTP_PROVIDERS_ENABLED must be true when stress HTTP settings "
                "are configured"
            )
        for setting_name, value in stress_urls.items():
            if value:
                normalized = _normalize_loopback_http_origin(value, setting_name=setting_name)
                object.__setattr__(self, setting_name, normalized)
                stress_urls[setting_name] = normalized

        ca_file = self.STRESS_FAKE_PROVIDER_CA_FILE.strip()
        if ca_file:
            ca_path = Path(ca_file).expanduser()
            if not ca_path.is_file():
                raise ValueError("STRESS_FAKE_PROVIDER_CA_FILE must identify an existing file")
            object.__setattr__(self, "STRESS_FAKE_PROVIDER_CA_FILE", str(ca_path.resolve()))
        if not ca_file and any(
            urlsplit(value).scheme == "https" for value in stress_urls.values() if value
        ):
            raise ValueError("HTTPS stress provider URLs require STRESS_FAKE_PROVIDER_CA_FILE")

        if self.ACCESS_TOKEN_COOKIE_PATH is None:
            object.__setattr__(self, "ACCESS_TOKEN_COOKIE_PATH", self.API_STR)

        if self.REFRESH_TOKEN_COOKIE_PATH is None:
            object.__setattr__(self, "REFRESH_TOKEN_COOKIE_PATH", f"{self.API_STR}/auth")

        if self.REFRESH_TOKEN_COOKIE_SECURE is None:
            object.__setattr__(self, "REFRESH_TOKEN_COOKIE_SECURE", self.ENVIRONMENT != "local")


settings = Settings()
