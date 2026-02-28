from collections import defaultdict

import httpx

from app.settings import get_settings
from app.models import Story


def _build_digest_message(stories: list[Story], title: str) -> str:
    lines = [f"*{title}*"]

    by_sector: dict[str, list[Story]] = defaultdict(list)
    for story in stories:
        by_sector[story.sector].append(story)

    for sector in sorted(by_sector.keys()):
        lines.append(f"\n*{sector}*")
        for story in sorted(by_sector[sector], key=lambda s: s.score, reverse=True)[:3]:
            lines.append(f"- [{story.title}]({story.url})")

    return "\n".join(lines)


def send_digest(stories: list[Story], *, title: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id or not stories:
        return

    message = _build_digest_message(stories, title)
    endpoint = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

    with httpx.Client(timeout=20.0) as client:
        client.post(
            endpoint,
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
        )
