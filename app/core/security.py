import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

_API_KEY_SALT = b"my-agent-v1"
_PASSWORD_ALGORITHM = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 260_000
_TOKEN_ALGORITHM = "HS256"


class InvalidToken(ValueError):
    pass


class ExpiredToken(ValueError):
    pass


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hmac.new(_API_KEY_SALT, api_key.encode("utf-8"), "sha256").hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PASSWORD_ITERATIONS,
    )
    return "$".join(
        (
            _PASSWORD_ALGORITHM,
            str(_PASSWORD_ITERATIONS),
            _b64encode(salt),
            _b64encode(digest),
        )
    )


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False

    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected_digest = _b64decode(digest_raw)
    except Exception:
        return False

    if algorithm != _PASSWORD_ALGORITHM or iterations <= 0:
        return False

    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def create_access_token(
    *,
    subject: str,
    secret: str,
    expires_in_seconds: int,
    extra: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + max(expires_in_seconds, 1),
    }
    if extra:
        payload.update(extra)

    header = {"alg": _TOKEN_ALGORITHM, "typ": "JWT"}
    header_segment = _b64encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_segment = _b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}"
    signature = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("ascii"),
        "sha256",
    ).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_access_token(token: str, *, secret: str) -> dict[str, Any]:
    try:
        header_segment, payload_segment, signature_segment = token.split(".", 2)
        signing_input = f"{header_segment}.{payload_segment}"
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            signing_input.encode("ascii"),
            "sha256",
        ).digest()
        actual_signature = _b64decode(signature_segment)
    except Exception as e:
        raise InvalidToken("Token 格式无效") from e

    if not hmac.compare_digest(actual_signature, expected_signature):
        raise InvalidToken("Token 签名无效")

    try:
        header = json.loads(_b64decode(header_segment))
        payload = json.loads(_b64decode(payload_segment))
    except Exception as e:
        raise InvalidToken("Token 内容无效") from e

    if header.get("alg") != _TOKEN_ALGORITHM:
        raise InvalidToken("Token 算法无效")

    try:
        expires_at = int(payload["exp"])
    except Exception as e:
        raise InvalidToken("Token 缺少过期时间") from e

    if expires_at <= int(time.time()):
        raise ExpiredToken("Token 已过期")

    return payload
