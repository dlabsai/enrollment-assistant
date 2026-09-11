import secrets
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, SessionDep, enforce_trusted_cookie_auth_request
from app.api.schemas import (
    AuthConfigOut,
    AuthSessionOut,
    TeamsSsoLogin,
    UserCreate,
    UserGroupOut,
    UserLogin,
    UserOut,
)
from app.core.config import settings
from app.core.entra_identity import EntraIdentity
from app.core.microsoft_auth_flows import (
    InvalidMicrosoftAuthFlowError,
    consume_microsoft_auth_flow,
    store_microsoft_auth_flow,
)
from app.core.microsoft_browser_sso import (
    MicrosoftBrowserSsoAuthenticationError,
    MicrosoftBrowserSsoConfigurationError,
    MicrosoftBrowserSsoUnavailableError,
    complete_microsoft_browser_sso,
    initiate_microsoft_browser_sso,
)
from app.core.rbac import SystemGroupSlug, get_effective_permission_map, get_group_for_slug
from app.core.refresh_tokens import create_refresh_token, revoke_refresh_token, rotate_refresh_token
from app.core.security import (
    create_access_token,
    get_password_hash,
    validate_password_strength,
    verify_and_update_password,
)
from app.core.teams_sso import validate_teams_sso_token
from app.models import RbacGroup, User
from app.utils import logger

router = APIRouter(prefix="/auth", tags=["authentication"])

_AUTH_COOKIE_NAMES = (settings.ACCESS_TOKEN_COOKIE_NAME, settings.REFRESH_TOKEN_COOKIE_NAME)
_MICROSOFT_AUTH_COOKIE_PATH = f"{settings.API_STR}/auth/microsoft"
_MICROSOFT_AUTH_ERROR_PATH = "/?auth_error=microsoft_sso"
_MAX_AUTH_RETURN_PATH_LENGTH = 2048


def _get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _get_refresh_cookie_path() -> str:
    return settings.REFRESH_TOKEN_COOKIE_PATH or f"{settings.API_STR}/auth"


def _get_access_cookie_path() -> str:
    return settings.ACCESS_TOKEN_COOKIE_PATH or settings.API_STR


def _get_refresh_cookie_secure() -> bool:
    return bool(settings.REFRESH_TOKEN_COOKIE_SECURE)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _browser_sso_email_is_allowed(email: str) -> bool:
    _, separator, domain = _normalize_email(email).rpartition("@")
    return (
        separator != ""
        and domain.casefold() == settings.BROWSER_SSO_ALLOWED_EMAIL_DOMAIN.strip().casefold()
    )


def _ensure_browser_sso_email_is_allowed(email: str) -> None:
    if not _browser_sso_email_is_allowed(email):
        raise MicrosoftBrowserSsoAuthenticationError(
            "Microsoft identity does not use an allowed email domain"
        )


def _get_cookie_samesite() -> Literal["lax", "strict", "none"]:
    return settings.REFRESH_TOKEN_COOKIE_SAMESITE


def _get_cookie_secure() -> bool:
    return _get_refresh_cookie_secure()


def _set_refresh_cookie(response: Response, token: str) -> None:
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    _set_cookie(
        response,
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path=_get_refresh_cookie_path(),
    )


def _set_access_cookie(response: Response, token: str) -> None:
    max_age = settings.JWT_EXPIRE_MINUTES * 60
    _set_cookie(
        response,
        key=settings.ACCESS_TOKEN_COOKIE_NAME,
        value=token,
        max_age=max_age,
        path=_get_access_cookie_path(),
    )


def _set_cookie(response: Response, *, key: str, value: str, max_age: int, path: str) -> None:
    response.set_cookie(
        key=key,
        value=value,
        httponly=True,
        secure=_get_cookie_secure(),
        samesite=_get_cookie_samesite(),
        max_age=max_age,
        path=path,
    )


def _clear_cookie_variants(response: Response, cookie_name: str, *, path: str) -> None:
    response.delete_cookie(
        key=cookie_name,
        path=path,
        httponly=True,
        secure=_get_cookie_secure(),
        samesite=_get_cookie_samesite(),
    )


def _clear_refresh_cookie(response: Response) -> None:
    _clear_cookie_variants(
        response, settings.REFRESH_TOKEN_COOKIE_NAME, path=_get_refresh_cookie_path()
    )


def _clear_access_cookie(response: Response) -> None:
    _clear_cookie_variants(
        response, settings.ACCESS_TOKEN_COOKIE_NAME, path=_get_access_cookie_path()
    )


def _set_microsoft_auth_flow_cookie(response: Response, browser_binding: str) -> None:
    response.set_cookie(
        key=settings.BROWSER_SSO_FLOW_COOKIE_NAME,
        value=browser_binding,
        httponly=True,
        secure=_get_cookie_secure(),
        samesite="lax",
        max_age=settings.BROWSER_SSO_FLOW_EXPIRE_MINUTES * 60,
        path=_MICROSOFT_AUTH_COOKIE_PATH,
    )


def _clear_microsoft_auth_flow_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.BROWSER_SSO_FLOW_COOKIE_NAME,
        path=_MICROSOFT_AUTH_COOKIE_PATH,
        httponly=True,
        secure=_get_cookie_secure(),
        samesite="lax",
    )


def _normalize_return_path(return_path: str) -> str:
    parsed = urlsplit(return_path)
    if (
        len(return_path) > _MAX_AUTH_RETURN_PATH_LENGTH
        or not return_path.startswith("/")
        or return_path.startswith("//")
        or "\\" in return_path
        or not return_path.isprintable()
        or parsed.scheme != ""
        or parsed.netloc != ""
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authentication return path"
        )
    return return_path


def _frontend_url(path: str) -> str:
    if settings.ENVIRONMENT != "local":
        return path
    return f"{settings.FRONTEND_HOST.rstrip('/')}{path}"


def _read_microsoft_auth_uri(flow: dict[str, Any]) -> str:
    auth_uri = flow.get("auth_uri")
    if not isinstance(auth_uri, str) or auth_uri == "":
        raise MicrosoftBrowserSsoUnavailableError(
            "Microsoft returned an incomplete browser auth flow"
        )
    return auth_uri


def _microsoft_auth_error_response() -> RedirectResponse:
    response = RedirectResponse(
        url=_frontend_url(_MICROSOFT_AUTH_ERROR_PATH), status_code=status.HTTP_302_FOUND
    )
    _clear_microsoft_auth_flow_cookie(response)
    return response


def _determine_group_slug(registration_token: str) -> SystemGroupSlug:
    token_to_role: list[tuple[str, SystemGroupSlug]] = []

    if settings.DEV_REGISTRATION_TOKEN:
        token_to_role.append((settings.DEV_REGISTRATION_TOKEN, SystemGroupSlug.DEV))

    if settings.ADMIN_REGISTRATION_TOKEN:
        token_to_role.append((settings.ADMIN_REGISTRATION_TOKEN, SystemGroupSlug.ADMIN))

    if settings.USER_REGISTRATION_TOKEN:
        token_to_role.append((settings.USER_REGISTRATION_TOKEN, SystemGroupSlug.USER))

    for token, role in token_to_role:
        if secrets.compare_digest(registration_token, token):
            return role

    msg = "Invalid registration token"
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


async def _create_authenticated_response(
    *, user: User, session: SessionDep, request: Request, response: Response
) -> AuthSessionOut:
    access_token = create_access_token(subject=str(user.id))
    refresh_token = await create_refresh_token(
        session,
        user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=_get_client_ip(request),
    )
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, refresh_token)
    return AuthSessionOut()


async def _get_user_by_entra_identity(
    *, identity: EntraIdentity, session: SessionDep
) -> User | None:
    return await session.scalar(
        select(User).where(
            User.entra_tenant_id == identity.tenant_id, User.entra_object_id == identity.object_id
        )
    )


async def _get_user_by_email(*, email: str, session: SessionDep) -> User | None:
    normalized_email = _normalize_email(email)
    return await session.scalar(select(User).where(func.lower(User.email) == normalized_email))


async def _build_user_out(session: SessionDep, user: User) -> UserOut:
    group = await session.get(RbacGroup, user.group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="RBAC group missing"
        )

    permissions = await get_effective_permission_map(session, user)

    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        group=UserGroupOut(id=group.id, slug=group.slug, name=group.name),
        permissions={
            permission_key.value: is_allowed for permission_key, is_allowed in permissions.items()
        },
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


async def _sync_entra_sso_user(*, identity: EntraIdentity, session: SessionDep) -> User:
    normalized_identity_email = _normalize_email(identity.email)
    user = await _get_user_by_entra_identity(identity=identity, session=session)
    if user is None:
        email_user = await _get_user_by_email(email=identity.email, session=session)
        if email_user is not None:
            if (email_user.entra_tenant_id is None and email_user.entra_object_id is None) or (
                email_user.entra_tenant_id == identity.tenant_id
                and email_user.entra_object_id == identity.object_id
            ):
                user = email_user
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Microsoft SSO email is already linked to another user",
                )

    if user is not None and not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")

    if user is None:
        user_group = await get_group_for_slug(session, SystemGroupSlug.USER)
        user = User(
            email=normalized_identity_email,
            name=identity.name,
            password_hash=get_password_hash(secrets.token_urlsafe(48)),
            entra_tenant_id=identity.tenant_id,
            entra_object_id=identity.object_id,
            is_active=True,
            group_id=user_group.id,
        )
        session.add(user)
    else:
        normalized_identity_email = _normalize_email(identity.email)
        if _normalize_email(user.email) != normalized_identity_email:
            conflicting_email_owner = await session.scalar(
                select(User).where(
                    func.lower(User.email) == normalized_identity_email, User.id != user.id
                )
            )
            if conflicting_email_owner is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Microsoft SSO email is already linked to another user",
                )

        user.email = normalized_identity_email
        user.name = identity.name
        user.entra_tenant_id = identity.tenant_id
        user.entra_object_id = identity.object_id

    await session.commit()
    await session.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")

    return user


@router.get("/config", response_model=AuthConfigOut)
async def get_auth_config() -> AuthConfigOut:
    return AuthConfigOut(
        browser_microsoft_sso_enabled=settings.BROWSER_SSO_ENABLED,
        password_registration_enabled=settings.PASSWORD_REGISTRATION_ENABLED,
    )


@router.get("/microsoft/start")
async def start_microsoft_browser_sso(session: SessionDep, return_to: str = "/") -> Response:
    if not settings.BROWSER_SSO_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser Microsoft sign in is not enabled",
        )

    normalized_return_path = _normalize_return_path(return_to)
    try:
        flow = await initiate_microsoft_browser_sso()
        auth_uri = _read_microsoft_auth_uri(flow)
        browser_binding = await store_microsoft_auth_flow(
            session, flow=flow, return_path=normalized_return_path
        )
    except MicrosoftBrowserSsoConfigurationError as exc:
        logger.error("Browser Microsoft SSO start failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser Microsoft sign in is not configured",
        ) from exc
    except MicrosoftBrowserSsoUnavailableError as exc:
        logger.error("Browser Microsoft SSO start failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser Microsoft sign in is temporarily unavailable",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected browser Microsoft SSO start failure")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser Microsoft sign in is temporarily unavailable",
        ) from exc

    redirect = RedirectResponse(url=auth_uri, status_code=status.HTTP_302_FOUND)
    _set_microsoft_auth_flow_cookie(redirect, browser_binding)
    return redirect


@router.get("/microsoft/callback")
async def complete_microsoft_browser_sso_callback(
    session: SessionDep, request: Request
) -> Response:
    state = request.query_params.get("state")
    browser_binding = request.cookies.get(settings.BROWSER_SSO_FLOW_COOKIE_NAME)
    if not state or not browser_binding:
        logger.warning("Browser Microsoft SSO callback is missing state or browser binding")
        return _microsoft_auth_error_response()

    try:
        stored_flow = await consume_microsoft_auth_flow(
            session, state=state, browser_binding=browser_binding
        )
        identity = await complete_microsoft_browser_sso(
            flow=stored_flow.flow, auth_response=dict(request.query_params.items())
        )
        _ensure_browser_sso_email_is_allowed(identity.email)
        user = await _sync_entra_sso_user(identity=identity, session=session)
        redirect = RedirectResponse(
            url=_frontend_url(stored_flow.return_path), status_code=status.HTTP_302_FOUND
        )
        _clear_microsoft_auth_flow_cookie(redirect)
        await _create_authenticated_response(
            user=user, session=session, request=request, response=redirect
        )
    except (
        InvalidMicrosoftAuthFlowError,
        MicrosoftBrowserSsoAuthenticationError,
        MicrosoftBrowserSsoConfigurationError,
        MicrosoftBrowserSsoUnavailableError,
        HTTPException,
    ) as exc:
        reason = str(exc) or type(exc).__name__
        logger.warning("Browser Microsoft SSO callback rejected: %s", reason)
        return _microsoft_auth_error_response()
    except Exception:
        logger.exception("Unexpected browser Microsoft SSO callback failure")
        return _microsoft_auth_error_response()

    return redirect


@router.post("/register", response_model=AuthSessionOut)
async def register_user(
    user_data: UserCreate, session: SessionDep, request: Request, response: Response
) -> Any:
    if not settings.PASSWORD_REGISTRATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Password registration is not enabled"
        )

    normalized_email = _normalize_email(user_data.email)

    if user_data.password != user_data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match"
        )

    try:
        validate_password_strength(user_data.password)
    except ValueError as exc:  # surfacing validation message to client
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    group_slug = _determine_group_slug(user_data.registration_token)

    # Check if user already exists
    existing_user = await _get_user_by_email(email=normalized_email, session=session)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Create new user
    hashed_password = get_password_hash(user_data.password)
    group = await get_group_for_slug(session, group_slug)
    user = User(
        email=normalized_email,
        name=user_data.name,
        password_hash=hashed_password,
        is_active=True,
        group_id=group.id,
    )

    session.add(user)
    await session.commit()
    await session.refresh(user)

    return await _create_authenticated_response(
        user=user, session=session, request=request, response=response
    )


@router.post("/login", response_model=AuthSessionOut)
async def login_user(
    user_data: UserLogin, session: SessionDep, request: Request, response: Response
) -> Any:
    user = await _get_user_by_email(email=user_data.email, session=session)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )

    password_valid, upgraded_password_hash = verify_and_update_password(
        user_data.password, user.password_hash
    )
    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")

    if upgraded_password_hash is not None and upgraded_password_hash != user.password_hash:
        user.password_hash = upgraded_password_hash
        await session.commit()
        await session.refresh(user)

    return await _create_authenticated_response(
        user=user, session=session, request=request, response=response
    )


@router.post("/teams-sso", response_model=AuthSessionOut)
async def login_user_with_teams_sso(
    payload: TeamsSsoLogin, session: SessionDep, request: Request, response: Response
) -> AuthSessionOut:
    identity = await validate_teams_sso_token(payload.token)
    user = await _sync_entra_sso_user(identity=identity, session=session)
    return await _create_authenticated_response(
        user=user, session=session, request=request, response=response
    )


@router.post("/refresh", response_model=AuthSessionOut)
async def refresh_session(session: SessionDep, request: Request, response: Response) -> Any:
    enforce_trusted_cookie_auth_request(request, cookie_names=_AUTH_COOKIE_NAMES)
    refresh_token = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token required"
        )

    user_id, new_refresh_token = await rotate_refresh_token(
        session,
        refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip_address=_get_client_ip(request),
    )

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials"
        )

    access_token = create_access_token(subject=str(user.id))
    _set_access_cookie(response, access_token)
    _set_refresh_cookie(response, new_refresh_token)
    return AuthSessionOut()


@router.post("/logout")
async def logout_user(session: SessionDep, request: Request, response: Response) -> dict[str, bool]:
    enforce_trusted_cookie_auth_request(request, cookie_names=_AUTH_COOKIE_NAMES)
    refresh_token = request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)
    if refresh_token:
        await revoke_refresh_token(session, refresh_token)
    _clear_access_cookie(response)
    _clear_refresh_cookie(response)
    _clear_microsoft_auth_flow_cookie(response)
    return {"success": True}


@router.get("/me", response_model=UserOut)
async def get_current_user_info(current_user: CurrentUser, session: SessionDep) -> UserOut:
    return await _build_user_out(session, current_user)


@router.get("/users", response_model=list[UserOut])
async def list_users(current_user: CurrentUser, session: SessionDep) -> list[UserOut]:
    if current_user.group.slug not in {"admin", "dev"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = list(result.scalars().all())
    return [await _build_user_out(session, user) for user in users]
