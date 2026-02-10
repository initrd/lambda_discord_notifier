"""
AWS Lambda handler for forwarding CloudWatch Alarms and EventBridge events
to a Discord channel via webhook.

Triggered by:
  - Amazon SNS (CloudWatch Alarm notifications)
  - Amazon EventBridge (scheduled rules, service events, custom events)

Environment Variables:
  DISCORD_WEBHOOK_URL  – Full Discord webhook URL (required)
  LOG_LEVEL            – Logging level, e.g. DEBUG, INFO (default: INFO)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from parsers import parse_cloudwatch_alarm, parse_eventbridge_event
from discord_client import send_discord_embed, DiscordEmbed

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger(__name__)
logger.setLevel(LOG_LEVEL)


# ---------------------------------------------------------------------------
# Lambda entry-point
# ---------------------------------------------------------------------------
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Route incoming event to the correct parser and post to Discord.

    Supports two event sources:
      1. **SNS** – ``event["Records"]`` contains one or more SNS messages,
         each wrapping a CloudWatch Alarm JSON payload.
      2. **EventBridge** – the *event* dict itself is the EventBridge
         envelope with ``source``, ``detail-type``, ``detail``, etc.

    Returns:
        A dict with ``statusCode`` and ``body`` for observability.
    """
    logger.info("Received event: %s", json.dumps(event, default=str))

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL environment variable is not set.")
        return _response(500, "Missing DISCORD_WEBHOOK_URL environment variable.")

    try:
        embeds = _build_embeds(event)
    except Exception:
        logger.exception("Failed to parse the incoming event.")
        return _response(500, "Event parsing failed.")

    if not embeds:
        logger.warning("No embeds were generated from the event.")
        return _response(200, "No actionable content found in event.")

    errors: list[str] = []
    for embed in embeds:
        try:
            send_discord_embed(webhook_url, embed)
        except Exception as exc:
            logger.exception("Failed to send embed to Discord.")
            errors.append(str(exc))

    if errors:
        return _response(502, f"Partial failure – {len(errors)} embed(s) failed.")

    return _response(200, f"Successfully sent {len(embeds)} notification(s).")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _build_embeds(event: dict[str, Any]) -> list[DiscordEmbed]:
    """Detect the event source and delegate to the right parser."""

    # SNS events always contain a "Records" key.
    if "Records" in event:
        embeds: list[DiscordEmbed] = []
        for record in event["Records"]:
            if record.get("EventSource") == "aws:sns":
                sns_message_raw: str = record["Sns"]["Message"]
                try:
                    sns_message = json.loads(sns_message_raw)
                except json.JSONDecodeError:
                    # Not JSON – treat as a plain-text SNS notification.
                    logger.info("SNS message is plain text, not JSON.")
                    embeds.append(
                        DiscordEmbed(
                            title="📢 SNS Notification",
                            description=sns_message_raw[:4096],
                            color=0x3498DB,
                            fields=[
                                ("Subject", record["Sns"].get("Subject", "N/A"), False),
                                ("Topic ARN", record["Sns"].get("TopicArn", "N/A"), False),
                            ],
                        )
                    )
                    continue

                # Check if it's a CloudWatch Alarm payload.
                if "AlarmName" in sns_message:
                    embeds.append(parse_cloudwatch_alarm(sns_message))
                else:
                    # Generic structured SNS message.
                    embeds.append(
                        DiscordEmbed(
                            title="📢 SNS Notification",
                            description=json.dumps(sns_message, indent=2)[:4096],
                            color=0x3498DB,
                            fields=[
                                ("Subject", record["Sns"].get("Subject", "N/A"), False),
                            ],
                        )
                    )
        return embeds

    # EventBridge events contain "source" and "detail-type".
    if "source" in event and "detail-type" in event:
        return [parse_eventbridge_event(event)]

    # Fallback – unknown source.
    logger.warning("Unrecognised event structure.")
    return [
        DiscordEmbed(
            title="⚠️ Unknown Event",
            description=f"```json\n{json.dumps(event, indent=2, default=str)[:4000]}\n```",
            color=0x95A5A6,
        )
    ]


def _response(status_code: int, body: str) -> dict[str, Any]:
    """Build a simple Lambda proxy response."""
    return {"statusCode": status_code, "body": body}
