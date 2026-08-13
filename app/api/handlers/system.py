from app.services.chat_service import health


async def handle_health() -> dict:
    return await health()

