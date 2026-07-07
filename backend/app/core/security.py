import re
from datetime import timedelta
from typing import Any

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from joserfc.jwt import JWTClaimsRegistry
from passlib.context import CryptContext
from passlib.exc import UnknownHashError as PasslibUnknownHashError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError as PwdlibUnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings
from app.utils import current_time_utc

_password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))
_legacy_pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt_sha256"], deprecated="auto")

_PASSWORD_MIN_LENGTH = 12


def _get_jwt_secret() -> str:
    if settings.JWT_SECRET_KEY is None or settings.JWT_SECRET_KEY == "":
        msg = "JWT_SECRET_KEY is not set"
        raise ValueError(msg)
    return settings.JWT_SECRET_KEY


def _get_jwt_key() -> OctKey:
    return OctKey.import_key(_get_jwt_secret())


def validate_password_strength(password: str) -> None:
    if len(password) < _PASSWORD_MIN_LENGTH:
        msg = f"Password must be at least {_PASSWORD_MIN_LENGTH} characters long"
        raise ValueError(msg)

    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must include at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must include at least one lowercase letter")
    if not re.search(r"\d", password):
        raise ValueError("Password must include at least one number")


def create_access_token(subject: str | Any, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = current_time_utc() + expires_delta
    else:
        expire = current_time_utc() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)

    to_encode = {"exp": expire, "sub": str(subject)}
    return jwt.encode(
        {"alg": settings.JWT_ALGORITHM, "typ": "JWT"},
        to_encode,
        _get_jwt_key(),
        algorithms=[settings.JWT_ALGORITHM],
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    verified, _ = verify_and_update_password(plain_password, hashed_password)
    return verified


def verify_and_update_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    try:
        return _password_hash.verify_and_update(plain_password, hashed_password)
    except PwdlibUnknownHashError:
        try:
            verified = _legacy_pwd_context.verify(plain_password, hashed_password)
        except PasslibUnknownHashError:
            return False, None

        if not verified:
            return False, None

        return True, _password_hash.hash(plain_password)


def get_password_hash(password: str) -> str:
    return _password_hash.hash(password)


def verify_token(token: str) -> str | None:
    try:
        decoded_token = jwt.decode(token, _get_jwt_key(), algorithms=[settings.JWT_ALGORITHM])
        claims = decoded_token.claims
        JWTClaimsRegistry(sub={"essential": True}, exp={"essential": True}).validate(claims)
        user_id = claims.get("sub")
        if not isinstance(user_id, str) or user_id == "":
            return None
    except JoseError:
        return None
    return user_id
