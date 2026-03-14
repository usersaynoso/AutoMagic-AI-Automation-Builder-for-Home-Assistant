"""Tests for prompt_builder and config flow prompt-adjacent helpers."""

from __future__ import annotations

import pytest

from custom_components.automagic.config_flow import (
    _pick_default_model,
    _get_model_temperature,
    _get_model_max_tokens,
)
from custom_components.automagic.prompt_builder import (
    SYSTEM_PROMPT,
    build_auto_clarification_answer,
    build_prompt,
)


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
        assert '"needs_clarification"' in SYSTEM_PROMPT
        assert '"clarifying_questions"' in SYSTEM_PROMPT
        assert "JSON" in SYSTEM_PROMPT
        assert "Keep the YAML concise" in SYSTEM_PROMPT
        assert "must start directly with alias:" in SYSTEM_PROMPT

    def test_system_prompt_forbids_invented_entities(self):
        """System prompt must tell LLM not to invent entity IDs."""
        assert "Never invent entity_ids" in SYSTEM_PROMPT
        assert "Do not invent notify services" in SYSTEM_PROMPT

    def test_system_prompt_supports_follow_up_questions(self):
        """Ambiguous requests should trigger clarification instead of empty YAML."""
        assert "do not guess" in SYSTEM_PROMPT
        assert "needs_clarification to true" in SYSTEM_PROMPT
        assert "Do not mark the task complete with an empty yaml string" in SYSTEM_PROMPT
        assert "ask a clarifying question instead of guessing" in SYSTEM_PROMPT
        assert "target entity, area, time, day, threshold, duration" in SYSTEM_PROMPT
        assert "follow-up change requests" in SYSTEM_PROMPT
        assert "follow-up questions about the current automation" in SYSTEM_PROMPT

    def test_system_prompt_supports_complex_multi_step_automations(self):
        """Complex branched requests should be represented as one complete automation."""
        assert "variables, choose blocks, delay/wait steps" in SYSTEM_PROMPT
        assert "Read the entire request as one combined condition/action sequence" in SYSTEM_PROMPT
        assert "Interpret wattage/watts/kW as power" in SYSTEM_PROMPT
        assert "whichever sensor triggered" in SYSTEM_PROMPT
        assert "Preserve exact thresholds, colors, brightness, flash counts" in SYSTEM_PROMPT
        assert "sibling variants such as left/right, L1/L2/L3, or numbered variants" in SYSTEM_PROMPT
        assert "whole listed set together" in SYSTEM_PROMPT
        assert "different threshold or state clauses clearly refer to different entity families" in SYSTEM_PROMPT
        assert "use the exact prompt clause instead of asking again" in SYSTEM_PROMPT
        assert "named automation concept" in SYSTEM_PROMPT
        assert "matching notify.* service is present" in SYSTEM_PROMPT
        assert 'current state is "unknown" or "unavailable"' in SYSTEM_PROMPT
        assert 'not between 9am and 5pm on a weekday' in SYSTEM_PROMPT
        assert "conditions, not as the automation's trigger schedule" in SYSTEM_PROMPT
        assert "boolean logic exactly when they combine OR and AND clauses" in SYSTEM_PROMPT
        assert "put the notification text under data:" in SYSTEM_PROMPT

    def test_system_prompt_accepts_explicit_entity_ids_and_sun_trigger(self):
        """Explicit entity IDs and the built-in sun trigger should not force extra clarification."""
        assert "explicitly names an entity_id" in SYSTEM_PROMPT
        assert "built-in sun trigger is allowed" in SYSTEM_PROMPT

    def test_system_prompt_accepts_obvious_name_matches_and_clear_time_phrases(self):
        """Obvious friendly-name matches and clear schedules should be treated as sufficient."""
        assert "exact or near-exact match" in SYSTEM_PROMPT
        assert "at 10am every morning" in SYSTEM_PROMPT
        assert "should not cause clarification" in SYSTEM_PROMPT

    def test_empty_entity_summary(self):
        """Should still produce valid messages with empty entity list."""
        result = build_prompt("Turn on lights", "")
        assert len(result) == 2
        assert "Available entities:" in result[1]["content"]

    def test_user_message_can_include_prompt_specific_guidance(self):
        """Prompt guidance should surface semantic entity-family mappings when available."""
        prompt = (
            "If any AC output voltage drops below 210 volts or any AC output current "
            "exceeds 15 amps while output power is above 100 watts, notify my iPhone."
        )
        entities = [
            {
                "entity_id": "sensor.victron_mk3_ac_output_voltage",
                "name": "AC Output Voltage",
                "domain": "sensor",
                "state": "230",
                "device_class": "voltage",
            },
            {
                "entity_id": "sensor.victron_mk3_ac_output_current",
                "name": "AC Output Current",
                "domain": "sensor",
                "state": "10",
                "device_class": "current",
            },
            {
                "entity_id": "sensor.victron_mk3_ac_output_power",
                "name": "AC Output Power",
                "domain": "sensor",
                "state": "1200",
                "device_class": "power",
            },
            {
                "entity_id": "notify.mobile_app_iphone_13",
                "name": "Notify Iphone 13",
                "domain": "notify",
                "state": "service",
                "device_class": "service",
            },
        ]
        summary = "\n".join(
            f"{entity['entity_id']} ({entity['name']}) [{entity['state']}]"
            for entity in entities
        )

        result = build_prompt(prompt, summary, entities)
        user_msg = result[1]["content"]

        assert "Prompt-specific guidance:" in user_msg
        assert "Semantic entity-family matches inferred from the request wording" in user_msg
        assert "power -> sensor.victron_mk3_ac_output_power" in user_msg
        assert "voltage -> sensor.victron_mk3_ac_output_voltage" in user_msg
        assert "current -> sensor.victron_mk3_ac_output_current" in user_msg
        assert "notification -> notify.mobile_app_iphone_13" in user_msg

    def test_entity_summary_uses_compact_entity_lines_when_entities_are_available(self):
        """Backend prompts should omit transient state noise when entity objects are available."""
        prompt = "Notify my iPhone if output power goes above 100 watts."
        entities = [
            {
                "entity_id": "sensor.victron_mk3_ac_output_power",
                "name": "AC Output Power",
                "domain": "sensor",
                "state": "120",
                "device_class": "power",
            },
            {
                "entity_id": "notify.mobile_app_iphone_13",
                "name": "Notify Iphone 13",
                "domain": "notify",
                "state": "service",
                "device_class": "service",
            },
        ]

        result = build_prompt(prompt, "ignored summary", entities)
        user_msg = result[1]["content"]

        assert "sensor.victron_mk3_ac_output_power (AC Output Power)" in user_msg
        assert "notify.mobile_app_iphone_13 (Notify Iphone 13)" in user_msg
        assert "[120]" not in user_msg
        assert "[service]" not in user_msg

    def test_auto_clarification_answer_resolves_grouped_sensor_questions(self):
        """Grouped sensor clarification loops should be answerable from the original prompt."""
        prompt = (
            "Monitor all three AC output phases. If any single phase voltage drops below 210 volts "
            "or any single phase current exceeds 15 amps while output power is above 100 watts, "
            "notify my iPhone."
        )
        result = {
            "summary": "The YAML cannot be completed without a specific voltage sensor.",
            "clarifying_questions": [
                "Which sensor should I use for AC Output Voltage? (sensor.victron_mk3_ac_output_voltage or sensor.victron_mk3_ac_output_voltage_l2 or sensor.victron_mk3_ac_output_voltage_l3)"
            ],
        }
        entities = [
            {
                "entity_id": "sensor.victron_mk3_ac_output_voltage",
                "name": "AC Output Voltage",
                "domain": "sensor",
                "state": "230",
                "device_class": "voltage",
            },
            {
                "entity_id": "sensor.victron_mk3_ac_output_voltage_l2",
                "name": "AC Output Voltage L2",
                "domain": "sensor",
                "state": "229",
                "device_class": "voltage",
            },
            {
                "entity_id": "sensor.victron_mk3_ac_output_voltage_l3",
                "name": "AC Output Voltage L3",
                "domain": "sensor",
                "state": "228",
                "device_class": "voltage",
            },
        ]

        answer = build_auto_clarification_answer(prompt, result, entities)

        assert "Use all matching entities in these sibling sets together" in answer
        assert "sensor.victron_mk3_ac_output_voltage_l2" in answer
        assert '"If any single phase voltage drops below 210 volts"' in answer

    def test_prompt_guidance_can_resolve_automation_guards_and_notification_targets(self):
        """Prompt guidance should surface resolved automation and notify matches."""
        prompt = (
            "If output power goes above 100 watts, notify my iPhone and do not run "
            "if the electricity balance automation is already active."
        )
        entities = [
            {
                "entity_id": "sensor.victron_mk3_ac_output_power",
                "name": "AC Output Power",
                "domain": "sensor",
                "state": "120",
                "device_class": "power",
            },
            {
                "entity_id": "notify.mobile_app_iphone_13",
                "name": "Notify Iphone 13",
                "domain": "notify",
                "state": "service",
                "device_class": "service",
            },
            {
                "entity_id": "automation.electricity_balance_above_ps1",
                "name": "Electricity balance ABOVE £1",
                "domain": "automation",
                "state": "on",
                "device_class": None,
            },
            {
                "entity_id": "automation.electricity_balance_low",
                "name": "Electricity balance low",
                "domain": "automation",
                "state": "off",
                "device_class": None,
            },
        ]
        summary = "\n".join(
            f"{entity['entity_id']} ({entity['name']}) [{entity['state']}]"
            for entity in entities
        )

        result = build_prompt(prompt, summary, entities)
        user_msg = result[1]["content"]

        assert "Resolved automation guard matches from the request" in user_msg
        assert "automation.electricity_balance_above_ps1" in user_msg
        assert "Resolved notification target matches from the request" in user_msg
        assert "notify.mobile_app_iphone_13" in user_msg

    def test_auto_clarification_answer_can_answer_guard_and_notify_questions(self):
        """Follow-up questions about guards and notification targets should be auto-resolved."""
        prompt = (
            "Notify my iPhone if output power goes above 100 watts, but do not run "
            "if the electricity balance automation is already active."
        )
        result = {
            "summary": "The YAML cannot be completed without the notification target and guard automation.",
            "clarifying_questions": [
                "Which notification target should be used for the iPhone alert?",
                "Should the automation only run if the electricity balance automation is not active?",
            ],
        }
        entities = [
            {
                "entity_id": "notify.mobile_app_iphone_13",
                "name": "Notify Iphone 13",
                "domain": "notify",
                "state": "service",
                "device_class": "service",
            },
            {
                "entity_id": "automation.electricity_balance_above_ps1",
                "name": "Electricity balance ABOVE £1",
                "domain": "automation",
                "state": "on",
                "device_class": None,
            },
            {
                "entity_id": "automation.electricity_balance_low",
                "name": "Electricity balance low",
                "domain": "automation",
                "state": "off",
                "device_class": None,
            },
        ]

        answer = build_auto_clarification_answer(prompt, result, entities)

        assert "Use these matching automation guard entities together" in answer
        assert "automation.electricity_balance_above_ps1" in answer
        assert "Use the matching notification target" in answer
        assert "notify.mobile_app_iphone_13" in answer


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
