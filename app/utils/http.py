from contextlib import contextmanager

import httpx

from app.core.config import get_settings


@contextmanager
def http_client():
    s = get_settings()
    with httpx.Client(timeout=s.HTTP_TIMEOUT) as client:
        yield client
