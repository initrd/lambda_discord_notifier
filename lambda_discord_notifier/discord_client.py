"""Discord webhook client for sending rich embed messages."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
import json

logger = logging.getLogger(__name__)

# Discord embed limits (https://discord.com/developers/docs/resources/message#embed-object)
MAX_TITLE_LEN = 256
MAX_DESC_LEN = 4096
MAX_FIELD_NAME_LEN = 256
MAX_FIELD_VALUE_LEN = 1024
MAX_FIELDS = 25
MAX_FOOTER_LEN = 2048


@dataclass
class DiscordEmbed:
    """Represents a single Discord embed object.

    Attributes:
        title:       Embed title (max 256 chars).
        description: Embed body text (max 4096 chars).
        color:       Sidebar colour as an integer (e.g. ``0xFF0000`` for red).
        fields:      List of ``(name, value, inline)`` tuples.
        footer_text: Optional footer text.
        timestamp:   ISO-8601 timestamp string shown in the embed footer.
    """

    title: str = ""
    description: str = ""
    color: int = 0x3498DB
    fields: list[tuple[str, str, bool]] = field(default_factory=list)
    footer_text: str = ""
    timestamp: str = ""

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Serialise to a Discord-API-compatible dict."""
        embed: dict[str, Any] = {}

        if self.title:
            embed["title"] = self.title[:MAX_TITLE_LEN]
        if self.description:
            embed["description"] = self.description[:MAX_DESC_LEN]
        if self.color:
            embed["color"] = self.color

        if self.fields:
            embed["fields"] = [
                {
                    "name": name[:MAX_FIELD_NAME_LEN] or "\u200b",
                    "value": value[:MAX_FIELD_VALUE_LEN] or "\u200b",
                    "inline": inline,
                }
                for name, value, inline in self.fields[:MAX_FIELDS]
            ]

        if self.footer_text:
            embed["footer"] = {"text": self.footer_text[:MAX_FOOTER_LEN]}

        if self.timestamp:
            embed["timestamp"] = self.timestamp

        return embed


def send_discord_embed(
    webhook_url: str,
    embed: DiscordEmbed,
    *,
    username: str = "AWS Notifier",
    avatar_url: str = "",
) -> None:
    """Post a single :class:`DiscordEmbed` to a Discord webhook.

    Uses only the standard library (``urllib``) so no external dependencies
    are required in the Lambda deployment package.

    Args:
        webhook_url: Full Discord webhook URL.
        embed:       The embed to send.
        username:    Override the webhook bot username.
        avatar_url:  Override the webhook bot avatar.

    Raises:
        ValueError:  If *webhook_url* is empty.
        RuntimeError: If the Discord API returns an error.
    """
    if not webhook_url:
        raise ValueError("webhook_url must not be empty.")

    payload: dict[str, Any] = {
        "username": username,
        "embeds": [embed.to_dict()],
    }
    if avatar_url:
        payload["avatar_url"] = avatar_url

    data = json.dumps(payload).encode("utf-8")

    req = urllib_request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AWS-Discord-Notifier/1.0",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=10) as resp:
            logger.info("Discord responded with HTTP %s", resp.status)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("Discord HTTP error %s: %s", exc.code, body)
        raise RuntimeError(f"Discord API error {exc.code}: {body}") from exc
    except URLError as exc:
        logger.error("Network error posting to Discord: %s", exc.reason)
        raise RuntimeError(f"Network error: {exc.reason}") from exc
