"""Tests for prompt_builder and config flow prompt-adjacent helpers."""

from __future__ import annotations

import pytest

from custom_components.automagic.config_flow import (
    _pick_default_model,
    _get_model_temperature,
    _get_model_max_tokens,
)
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

    def test_system_prompt_requires_upfront_blocking_guards(self):
        """System prompt should require do-not-run guards in top-level conditions."""
        assert "top-level conditions: block" in SYSTEM_PROMPT
        assert "not as a choose: branch inside" in SYSTEM_PROMPT

    def test_empty_entity_summary(self):
        """Should still produce valid messages with empty entity list."""
        result = build_prompt("Turn on lights", "")
        assert len(result) == 2
        assert "Available entities:" in result[1]["content"]


class TestPickDefaultModel:
    """Tests for automatic default model selection."""

    def test_prefers_best_known_model(self):
        """Prefer stronger recommended models when available."""
        models = ["llama3.2:latest", "qwen2.5:7b", "mistral-nemo"]
        assert _pick_default_model(models) == "qwen2.5:7b"

    def test_matches_prefixed_variant(self):
        """Allow variant suffixes like context-tuned or quantized tags."""
        models = ["qwen2.5:3b-16k", "llama3.2:latest"]
        assert _pick_default_model(models) == "qwen2.5:3b-16k"

    def test_falls_back_to_first_model(self):
        """Use the first discovered model if none match preferences."""
        models = ["custom-model", "another-model"]
        assert _pick_default_model(models) == "custom-model"

    def test_empty_model_list_returns_empty_string(self):
        """No models means no auto-detected default."""
        assert _pick_default_model([]) == ""


class TestModelTemperature:
    """Tests for per-model temperature selection."""

    def test_known_model_gets_specific_temp(self):
        assert _get_model_temperature("qwen2.5:7b") == 0.15
        assert _get_model_temperature("gpt-4o-mini") == 0.1
        assert _get_model_temperature("mistral-nemo:latest") == 0.2

    def test_unknown_model_gets_default(self):
        from custom_components.automagic.const import DEFAULT_TEMPERATURE
        assert _get_model_temperature("totally-unknown-model") == DEFAULT_TEMPERATURE


class TestModelMaxTokens:
    """Tests for per-model max_tokens selection."""

    def test_known_cloud_model(self):
        assert _get_model_max_tokens("gpt-4o") == 4096

    def test_unknown_model_gets_local_default(self):
        from custom_components.automagic.const import DEFAULT_LOCAL_MAX_TOKENS
        assert _get_model_max_tokens("custom-local-model") == DEFAULT_LOCAL_MAX_TOKENS
