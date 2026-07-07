from uuid import UUID  # noqa: TC003

from httpx import AsyncClient

from app.core.config import settings
from app.core.security import create_access_token


def authenticate_client(client: AsyncClient, user_id: UUID) -> None:
    client.cookies.set(settings.ACCESS_TOKEN_COOKIE_NAME, create_access_token(str(user_id)))
    client.headers["Origin"] = str(client.base_url).rstrip("/")
