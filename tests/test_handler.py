"""Unit tests for the Lambda Discord notifier."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure the Lambda source is importable.
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda_discord_notifier"))

from handler import lambda_handler, _build_embeds  # noqa: E402
from parsers import parse_cloudwatch_alarm, parse_eventbridge_event  # noqa: E402
from discord_client import DiscordEmbed, send_discord_embed  # noqa: E402


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------

SAMPLE_CLOUDWATCH_ALARM_MESSAGE: dict = {
    "AlarmName": "HighCPUUtilization",
    "AlarmDescription": "CPU utilization exceeded 80% for 5 minutes.",
    "AWSAccountId": "123456789012",
    "NewStateValue": "ALARM",
    "NewStateReason": "Threshold Crossed: 1 datapoint [85.0 (10/02/26 06:00:00)] was >= threshold (80.0).",
    "StateChangeTime": "2026-02-10T06:05:00.000+0000",
    "Region": "ap-south-1",
    "AlarmArn": "arn:aws:cloudwatch:ap-south-1:123456789012:alarm:HighCPUUtilization",
    "OldStateValue": "OK",
    "Trigger": {
        "MetricName": "CPUUtilization",
        "Namespace": "AWS/EC2",
        "StatisticType": "Statistic",
        "Statistic": "AVERAGE",
        "Unit": None,
        "Dimensions": [
            {"value": "i-0123456789abcdef0", "name": "InstanceId"}
        ],
        "Period": 300,
        "EvaluationPeriods": 1,
        "ComparisonOperator": "GreaterThanOrEqualToThreshold",
        "Threshold": 80.0,
    },
}

SAMPLE_SNS_EVENT: dict = {
    "Records": [
        {
            "EventSource": "aws:sns",
            "EventVersion": "1.0",
            "Sns": {
                "Type": "Notification",
                "MessageId": "msg-001",
                "TopicArn": "arn:aws:sns:ap-south-1:123456789012:CloudWatchAlarms",
                "Subject": "ALARM: HighCPUUtilization",
                "Message": json.dumps(SAMPLE_CLOUDWATCH_ALARM_MESSAGE),
                "Timestamp": "2026-02-10T06:05:01.000Z",
            },
        }
    ]
}

SAMPLE_ECS_TASK_ChangeEvent: dict = {
    "version": "0",
    "id": "12345678-1234-1234-1234-123456789012",
    "detail-type": "ECS Task State Change",
    "source": "aws.ecs",
    "account": "123456789012",
    "time": "2026-02-10T06:10:00Z",
    "region": "ap-south-1",
    "resources": ["arn:aws:ecs:ap-south-1:123456789012:task/my-cluster/12345678901234567890"],
    "detail": {
        "taskArn": "arn:aws:ecs:ap-south-1:123456789012:task/my-cluster/12345678901234567890",
        "lastStatus": "STOPPED",
        "stoppedReason": "Essential container in task exited",
    },
}

SAMPLE_ECS_SERVICE_ACTION_EVENT: dict = {
    "version": "0",
    "id": "12345678-5678-5678-5678-123456789012",
    "detail-type": "ECS Service Action",
    "source": "aws.ecs",
    "account": "123456789012",
    "time": "2026-02-10T07:00:00Z",
    "region": "ap-south-1",
    "resources": ["arn:aws:ecs:ap-south-1:123456789012:service/my-cluster/my-service"],
    "detail": {
        "eventName": "SERVICE_STEADY_STATE",
        "clusterArn": "arn:aws:ecs:ap-south-1:123456789012:cluster/my-cluster",
        "reason": "The service has reached a steady state.",
    },
}


# ---------------------------------------------------------------------------
# Tests – parsers
# ---------------------------------------------------------------------------
class TestCloudWatchAlarmParser(unittest.TestCase):
    """Tests for ``parsers.parse_cloudwatch_alarm``."""

    def test_alarm_state_produces_red_embed(self) -> None:
        embed = parse_cloudwatch_alarm(SAMPLE_CLOUDWATCH_ALARM_MESSAGE)
        self.assertIsInstance(embed, DiscordEmbed)
        self.assertEqual(embed.color, 0xE74C3C)
        self.assertIn("HighCPUUtilization", embed.title)

    def test_ok_state_produces_green_embed(self) -> None:
        msg = {**SAMPLE_CLOUDWATCH_ALARM_MESSAGE, "NewStateValue": "OK", "OldStateValue": "ALARM"}
        embed = parse_cloudwatch_alarm(msg)
        self.assertEqual(embed.color, 0x2ECC71)

    def test_insufficient_data_produces_amber_embed(self) -> None:
        msg = {**SAMPLE_CLOUDWATCH_ALARM_MESSAGE, "NewStateValue": "INSUFFICIENT_DATA"}
        embed = parse_cloudwatch_alarm(msg)
        self.assertEqual(embed.color, 0xF39C12)

    def test_fields_contain_metric_info(self) -> None:
        embed = parse_cloudwatch_alarm(SAMPLE_CLOUDWATCH_ALARM_MESSAGE)
        field_names = [f[0] for f in embed.fields]
        self.assertIn("Metric", field_names)
        self.assertIn("Dimensions", field_names)

    def test_state_transition_field(self) -> None:
        embed = parse_cloudwatch_alarm(SAMPLE_CLOUDWATCH_ALARM_MESSAGE)
        transition = next(f for f in embed.fields if f[0] == "State Transition")
        self.assertIn("OK", transition[1])
        self.assertIn("ALARM", transition[1])


class TestEventBridgeParser(unittest.TestCase):
    """Tests for ``parsers.parse_eventbridge_event``."""

    def test_ecs_task_change_format(self) -> None:
        embed = parse_eventbridge_event(SAMPLE_ECS_TASK_ChangeEvent)
        self.assertIn("ECS Task State Change", embed.title)
        self.assertIn("STOPPED", embed.description)
        self.assertIn("Essential container", embed.description)

    def test_ecs_service_action_format(self) -> None:
        embed = parse_eventbridge_event(SAMPLE_ECS_SERVICE_ACTION_EVENT)
        self.assertIn("ECS Service Action", embed.title)
        self.assertIn("SERVICE_STEADY_STATE", embed.description)
        self.assertIn("my-cluster", embed.description)
        self.assertIn("steady state", embed.description)

    def test_source_in_footer(self) -> None:
        embed = parse_eventbridge_event(SAMPLE_ECS_TASK_ChangeEvent)
        self.assertIn("aws.ecs", embed.footer_text)

    def test_resources_field_present(self) -> None:
        embed = parse_eventbridge_event(SAMPLE_ECS_TASK_ChangeEvent)
        field_names = [f[0] for f in embed.fields]
        self.assertIn("Resources", field_names)


# ---------------------------------------------------------------------------
# Tests – handler routing
# ---------------------------------------------------------------------------
class TestHandlerRouting(unittest.TestCase):
    """Tests for ``handler._build_embeds`` routing logic."""

    def test_sns_event_routes_to_cloudwatch_parser(self) -> None:
        embeds = _build_embeds(SAMPLE_SNS_EVENT)
        self.assertEqual(len(embeds), 1)
        self.assertIn("CloudWatch", embeds[0].title)

    def test_eventbridge_event_routes_to_eb_parser(self) -> None:
        embeds = _build_embeds(SAMPLE_ECS_TASK_ChangeEvent)
        self.assertEqual(len(embeds), 1)
        self.assertIn("EventBridge", embeds[0].title)

    def test_plain_text_sns_message(self) -> None:
        event = {
            "Records": [
                {
                    "EventSource": "aws:sns",
                    "Sns": {
                        "Message": "This is just plain text.",
                        "Subject": "Test",
                        "TopicArn": "arn:aws:sns:us-east-1:123456789012:TestTopic",
                    },
                }
            ]
        }
        embeds = _build_embeds(event)
        self.assertEqual(len(embeds), 1)
        self.assertIn("SNS", embeds[0].title)

    def test_unknown_event_fallback(self) -> None:
        embeds = _build_embeds({"foo": "bar"})
        self.assertEqual(len(embeds), 1)
        self.assertIn("Unknown", embeds[0].title)


# ---------------------------------------------------------------------------
# Tests – handler end-to-end (Discord call mocked)
# ---------------------------------------------------------------------------
class TestLambdaHandler(unittest.TestCase):
    """Integration-style tests for ``handler.lambda_handler``."""

    @patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"})
    @patch("handler.send_discord_embed")
    def test_sns_event_sends_one_embed(self, mock_send: MagicMock) -> None:
        result = lambda_handler(SAMPLE_SNS_EVENT, None)
        self.assertEqual(result["statusCode"], 200)
        mock_send.assert_called_once()

    @patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"})
    @patch("handler.send_discord_embed")
    def test_eventbridge_event_sends_one_embed(self, mock_send: MagicMock) -> None:
        result = lambda_handler(SAMPLE_ECS_TASK_ChangeEvent, None)
        self.assertEqual(result["statusCode"], 200)
        mock_send.assert_called_once()

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_webhook_url_returns_500(self) -> None:
        result = lambda_handler(SAMPLE_SNS_EVENT, None)
        self.assertEqual(result["statusCode"], 500)
        self.assertIn("Missing", result["body"])

    @patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"})
    @patch("handler.send_discord_embed", side_effect=RuntimeError("Discord down"))
    def test_discord_failure_returns_502(self, mock_send: MagicMock) -> None:
        result = lambda_handler(SAMPLE_SNS_EVENT, None)
        self.assertEqual(result["statusCode"], 502)


# ---------------------------------------------------------------------------
# Tests – DiscordEmbed serialisation
# ---------------------------------------------------------------------------
class TestDiscordEmbed(unittest.TestCase):

    def test_to_dict_basic(self) -> None:
        embed = DiscordEmbed(title="Hello", description="World", color=0xFF0000)
        d = embed.to_dict()
        self.assertEqual(d["title"], "Hello")
        self.assertEqual(d["color"], 0xFF0000)

    def test_fields_are_serialised(self) -> None:
        embed = DiscordEmbed(fields=[("Name", "Value", True)])
        d = embed.to_dict()
        self.assertEqual(len(d["fields"]), 1)
        self.assertTrue(d["fields"][0]["inline"])

    def test_long_title_is_truncated(self) -> None:
        embed = DiscordEmbed(title="A" * 300)
        d = embed.to_dict()
        self.assertEqual(len(d["title"]), 256)

    def test_empty_fields_default(self) -> None:
        embed = DiscordEmbed()
        d = embed.to_dict()
        self.assertNotIn("fields", d)


if __name__ == "__main__":
    unittest.main()
