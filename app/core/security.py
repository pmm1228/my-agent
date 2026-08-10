import hmac
import secrets

_API_KEY_SALT = b"my-agent-v1"


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hmac.new(_API_KEY_SALT, api_key.encode("utf-8"), "sha256").hexdigest()
