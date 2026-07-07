from typing import Annotated, Any, Literal

from pydantic import AnyUrl, BeforeValidator, computed_field
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

# from app.core.constants import DEFAULT_DEV_USER_EMAIL


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
    CHATBOT_MODEL_MAX_TOKENS: int = 0

    # Model for developer investigation chats.
    INVESTIGATION_MODEL: str = "azure/gpt-5.4"
    INVESTIGATION_REASONING_EFFORT: Literal["none", "low", "medium", "high", "xhigh"] = "high"

    # Model for guardrails
    GUARDRAIL_MODEL: str = "azure/gpt-5.4"
    GUARDRAIL_MODEL_TEMPERATURE: float = 0.1
    GUARDRAIL_MODEL_MAX_TOKENS: int = 0

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

    # Model for summarization
    SUMMARIZER_MODEL: str = "azure/gpt-5.4-mini"

    # Model for post-response grounding source selection
    GROUNDING_MODEL: str = "azure/gpt-5.4"
    GROUNDING_REASONING_EFFORT: Literal["none", "low", "medium", "high", "xhigh"] = "medium"

    # HTTP request timeout for LLM calls (seconds)
    LLM_REQUEST_TIMEOUT: float = 5 * 60.0  # 5 minutes

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

    def model_post_init(self, __context: Any, /) -> None:
        if self.ACCESS_TOKEN_COOKIE_PATH is None:
            object.__setattr__(self, "ACCESS_TOKEN_COOKIE_PATH", self.API_STR)

        if self.REFRESH_TOKEN_COOKIE_PATH is None:
            object.__setattr__(self, "REFRESH_TOKEN_COOKIE_PATH", f"{self.API_STR}/auth")

        if self.REFRESH_TOKEN_COOKIE_SECURE is None:
            object.__setattr__(self, "REFRESH_TOKEN_COOKIE_SECURE", self.ENVIRONMENT != "local")


settings = Settings()
