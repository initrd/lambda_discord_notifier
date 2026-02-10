"""Formatter for ECS Task State Change events."""

from __future__ import annotations
from typing import Any
from ..registry import register_parser


@register_parser("ECS Task State Change")
def format_ecs_task_change(detail: dict[str, Any]) -> str:
    """Format ECS Task State Change details into a readable summary."""
    cluster_arn = detail.get("clusterArn", "")
    task_arn = detail.get("taskArn", "")
    last_status = detail.get("lastStatus", "UNKNOWN")
    desired_status = detail.get("desiredStatus", "UNKNOWN")
    stopped_reason = detail.get("stoppedReason") or detail.get("stopCode") or "N/A"
    
    # Extract short names from ARNs
    cluster_name = cluster_arn.split("/")[-1] if "/" in cluster_arn else cluster_arn
    task_id = task_arn.split("/")[-1] if "/" in task_arn else task_arn

    lines = [
        f"**Cluster:** `{cluster_name}`",
        f"**Task:** `{task_id}`",
        f"**Status:** `{last_status}` (Desired: `{desired_status}`)",
        f"**Reason:** {stopped_reason}",
        "",
        "**Containers:**"
    ]

    containers = detail.get("containers", [])
    if containers:
        for c in containers:
            name = c.get("name", "unknown")
            status = c.get("lastStatus", "UNKNOWN")
            exit_code = c.get("exitCode", "N/A")
            reason = c.get("reason", "")
            
            # Add an alert icon if the container failed
            icon = "✅" if exit_code == 0 else "⚠️"
            if status != "RUNNING" and status != "STOPPED":
                icon = "🔄"  # Pending/Provisioning

            details = f"`{name}`: {status}"
            if exit_code != "N/A":
                details += f" (Exit: {exit_code})"
            if reason:
                details += f" - {reason}"
            
            lines.append(f"{icon} {details}")
    else:
        lines.append("_No container info available_")

    return "\n".join(lines)


@register_parser("ECS Service Action")
def format_ecs_service_action(detail: dict[str, Any]) -> str:
    """Format ECS Service Action details."""
    event_name = detail.get("eventName", "Unknown Event")
    event_type = detail.get("eventType", "INFO")
    cluster_arn = detail.get("clusterArn", "")
    
    # Extract short names
    cluster_name = cluster_arn.split("/")[-1] if "/" in cluster_arn else cluster_arn
    
    # Map event type to emoji
    emoji = ""
    if event_type == "WARN":
        emoji = "⚠️ "
    elif event_type == "ERROR":
        emoji = "🔴 "
    elif event_type == "INFO":
        emoji = "ℹ️ "
    
    # Common fields for service actions
    lines = [
        f"**Event:** {emoji}`{event_name}`",
        f"**Type:** `{event_type}`",
        f"**Cluster:** `{cluster_name}`",
    ]

    # Add extra context if available (depends on specific eventName)
    if "capacityProviderArns" in detail:
        lines.append(f"**Capacity Providers:** {', '.join(detail['capacityProviderArns'])}")
        
    if "reason" in detail:
        lines.append(f"**Reason:** {detail['reason']}")

    return "\n".join(lines)
