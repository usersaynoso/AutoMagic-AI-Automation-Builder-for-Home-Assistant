"""Tests for prompt_builder module."""

from __future__ import annotations

import pytest

from custom_components.automagic.prompt_builder import build_prompt, SYSTEM_PROMPT


class TestBuildPrompt:
    """Tests for the build_prompt function."""

    def test_returns_two_messages(self):
        """Should return system + user messages."""
        result = build_prompt("Turn on the lights", "light.lamp (Lamp) [off]")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_system_message_contains_syntax_rules(self):
        """System message must enforce 2024.10+ syntax."""
        result = build_prompt("test", "test")
        system = result[0]["content"]
        assert "triggers:" in system
        assert "actions:" in system
        assert "NEVER use 'service:'" in system
        assert "NOT 'platform:'" in system

    def test_user_message_contains_entity_summary(self):
        """User message should include the entity list."""
        entity_summary = "light.lamp (Lamp) [on]\nsensor.temp (Temperature) [22]"
        result = build_prompt("Turn on the lights", entity_summary)
        user_msg = result[1]["content"]
        assert "light.lamp (Lamp) [on]" in user_msg
        assert "sensor.temp (Temperature) [22]" in user_msg

    def test_user_message_contains_user_input(self):
        """User message should include the user's request."""
        user_input = "Flash the hallway lights red when the front door opens"
        result = build_prompt(user_input, "light.hallway (Hallway) [off]")
        user_msg = result[1]["content"]
        assert user_input in user_msg

    def test_user_message_format(self):
        """User message should have the correct format structure."""
        result = build_prompt("Do something", "entity.one (One) [on]")
        user_msg = result[1]["content"]
        assert user_msg.startswith("Available entities:")
        assert "Create an automation for:" in user_msg

    def test_system_prompt_requires_json_output(self):
        """System prompt must instruct the LLM to output JSON."""
        assert '"yaml"' in SYSTEM_PROMPT
        assert '"summary"' in SYSTEM_PROMPT
        assert "JSON" in SYSTEM_PROMPT

    def test_system_prompt_forbids_invented_entities(self):
        """System prompt must tell LLM not to invent entity IDs."""
        assert "Never invent entity_ids" in SYSTEM_PROMPT

    def test_empty_entity_summary(self):
        """Should still produce valid messages with empty entity list."""
        result = build_prompt("Turn on lights", "")
        assert len(result) == 2
        assert "Available entities:" in result[1]["content"]
