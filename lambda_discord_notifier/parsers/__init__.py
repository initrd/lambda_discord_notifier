"""Main entry point for parsers."""

from __future__ import annotations

import json
import logging
from typing import Any

from discord_client import DiscordEmbed
from .registry import get_detail_parser

# Import detail parsers so they register themselves
from .details import ecs

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_ALARM_STATE_COLOURS: dict[str, int] = {
    "ALARM": 0xE74C3C,          # red
    "OK": 0x2ECC71,             # green
    "INSUFFICIENT_DATA": 0xF39C12,  # amber
}

_ALARM_STATE_EMOJI: dict[str, str] = {
    "ALARM": "🔴",
    "OK": "🟢",
    "INSUFFICIENT_DATA": "🟡",
}

_EVENTBRIDGE_SOURCE_COLOURS: dict[str, int] = {
    "aws.ec2": 0xF4A460,
    "aws.ecs": 0xFF6347,
    "aws.rds": 0x4169E1,
    "aws.s3": 0x3CB371,
    "aws.guardduty": 0xDC143C,
    "aws.health": 0xFF8C00,
    "aws.codepipeline": 0x1E90FF,
    "aws.codebuild": 0x6A5ACD,
    "aws.lambda": 0xFFA500,
}


def parse_cloudwatch_alarm(message: dict[str, Any]) -> DiscordEmbed:
    """Parse a CloudWatch Alarm SNS message into a :class:`DiscordEmbed`."""
    alarm_name: str = message.get("AlarmName", "Unknown Alarm")
    new_state: str = message.get("NewStateValue", "UNKNOWN")
    old_state: str = message.get("OldStateValue", "UNKNOWN")
    reason: str = message.get("NewStateReason", "")
    description: str = message.get("AlarmDescription") or ""
    region: str = message.get("Region", "")
    account_id: str = message.get("AWSAccountId", "")
    namespace: str = message.get("Trigger", {}).get("Namespace", "")
    metric_name: str = message.get("Trigger", {}).get("MetricName", "")
    state_change_time: str = message.get("StateChangeTime", "")
    dimensions: list[dict[str, str]] = message.get("Trigger", {}).get("Dimensions", [])

    emoji = _ALARM_STATE_EMOJI.get(new_state, "⚪")
    colour = _ALARM_STATE_COLOURS.get(new_state, 0x95A5A6)

    fields: list[tuple[str, str, bool]] = [
        ("State Transition", f"`{old_state}` → `{new_state}`", True),
        ("Region", region or "N/A", True),
        ("Account", account_id or "N/A", True),
    ]

    if namespace or metric_name:
        fields.append(("Metric", f"`{namespace}/{metric_name}`", False))

    if dimensions:
        dim_text = ", ".join(
            f"`{d.get('name', '?')}={d.get('value', '?')}`" for d in dimensions
        )
        fields.append(("Dimensions", dim_text, False))

    if reason:
        fields.append(("Reason", reason[:1024], False))

    body = description if description else f"The alarm **{alarm_name}** is now in **{new_state}** state."

    return DiscordEmbed(
        title=f"{emoji} CloudWatch Alarm: {alarm_name}",
        description=body[:4096],
        color=colour,
        fields=fields,
        footer_text="CloudWatch Alarm Notification",
        timestamp=state_change_time,
    )


def parse_eventbridge_event(event: dict[str, Any]) -> DiscordEmbed:
    """Parse an EventBridge event envelope into a :class:`DiscordEmbed`."""
    source = event.get("source", "unknown")
    if isinstance(source, list):
        source = source[0] if source else "unknown"

    detail_type = event.get("detail-type", "Unknown Event")
    if isinstance(detail_type, list):
        detail_type = detail_type[0] if detail_type else "Unknown Event"

    detail: dict[str, Any] = event.get("detail", {})
    region: str = event.get("region", "")
    account: str = event.get("account", "")
    event_time: str = event.get("time", "")
    event_id: str = event.get("id", "")
    resources: list[str] = event.get("resources", [])

    colour = _EVENTBRIDGE_SOURCE_COLOURS.get(source, 0x7289DA)

    # Check registry for a custom formatter
    formatter = get_detail_parser(detail_type)
    
    if formatter:
        try:
            description = formatter(detail)
        except Exception:
            logger.exception("Custom parser for '%s' failed", detail_type)
            description = _default_json_formatter(detail)
    else:
        description = _default_json_formatter(detail)

    fields: list[tuple[str, str, bool]] = [
        ("Source", f"`{source}`", True),
        ("Detail Type", detail_type, True),
        ("Region", region or "N/A", True),
        ("Account", account or "N/A", True),
    ]

    if resources:
        resources_text = "\n".join(f"• `{r}`" for r in resources[:10])
        fields.append(("Resources", resources_text[:1024], False))

    if event_id:
        fields.append(("Event ID", f"`{event_id}`", False))

    return DiscordEmbed(
        title=f"📡 EventBridge: {detail_type}",
        description=description,
        color=colour,
        fields=fields,
        footer_text=f"EventBridge · {source}",
        timestamp=event_time,
    )


def _default_json_formatter(detail: dict[str, Any]) -> str:
    """Default formatter: pretty-print the JSON."""
    detail_json = json.dumps(detail, indent=2, default=str)
    if len(detail_json) > 3900:
        detail_json = detail_json[:3900] + "\n… (truncated)"
    return f"```json\n{detail_json}\n```"
