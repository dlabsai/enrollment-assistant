from datetime import timedelta

from passlib.context import CryptContext
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.security import (
    create_access_token,
    get_password_hash,
    verify_and_update_password,
    verify_password,
    verify_token,
)


def test_get_password_hash_uses_argon2() -> None:
    password_hash = get_password_hash("StrongPassword123")

    assert password_hash.startswith("$argon2id$")
    assert verify_password("StrongPassword123", password_hash)


def test_verify_and_update_password_upgrades_bcrypt_hashes() -> None:
    legacy_bcrypt_hash = BcryptHasher().hash("StrongPassword123")

    verified, upgraded_hash = verify_and_update_password("StrongPassword123", legacy_bcrypt_hash)

    assert verified is True
    assert upgraded_hash is not None
    assert upgraded_hash.startswith("$argon2id$")


def test_verify_and_update_password_upgrades_pbkdf2_hashes() -> None:
    legacy_pbkdf2_hash = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto").hash(
        "StrongPassword123"
    )

    verified, upgraded_hash = verify_and_update_password("StrongPassword123", legacy_pbkdf2_hash)

    assert verified is True
    assert upgraded_hash is not None
    assert upgraded_hash.startswith("$argon2id$")


def test_create_access_token_round_trips_subject() -> None:
    token = create_access_token("user-123")

    assert verify_token(token) == "user-123"


def test_verify_token_returns_none_for_tampered_token() -> None:
    token = create_access_token("user-123")
    token_parts = token.split(".")
    tampered_signature = f"{token_parts[2][:-1]}{'a' if token_parts[2][-1] != 'a' else 'b'}"
    tampered_token = ".".join([token_parts[0], token_parts[1], tampered_signature])

    assert verify_token(tampered_token) is None


def test_verify_token_returns_none_for_expired_token() -> None:
    token = create_access_token("user-123", expires_delta=timedelta(seconds=-1))

    assert verify_token(token) is None
