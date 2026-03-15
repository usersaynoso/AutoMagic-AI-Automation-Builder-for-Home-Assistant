"""Deterministically assemble Home Assistant automation YAML from intent JSON.

Example: simple time trigger
input intent:
{
  "alias": "Morning lights",
  "description": "Turns on a light at 07:00.",
  "mode": "single",
  "triggers": [{"type": "time", "at": "07:00:00"}],
  "conditions": [],
  "action_sequence": [
    {
      "step_type": "service_call",
      "action": "light.turn_on",
      "target_entity_ids": ["light.example"],
    }
  ],
}

expected YAML:
alias: Morning lights
description: Turns on a light at 07:00.
triggers:
  - trigger: time
    at: '07:00:00'
conditions: []
actions:
  - action: light.turn_on
    target:
      entity_id: light.example
mode: single

Example: state trigger with service call
input intent:
{
  "alias": "Door hallway",
  "description": "Turns on the hallway light when the door opens.",
  "mode": "restart",
  "triggers": [{"type": "state", "entity_id": "binary_sensor.door", "to": "on"}],
  "conditions": [],
  "action_sequence": [
    {
      "step_type": "service_call",
      "action": "light.turn_on",
      "target_entity_ids": ["light.hallway"],
      "data": {"brightness_pct": 60}
    }
  ],
}

Example: numeric_state trigger with conditions
input intent:
{
  "alias": "Power warning",
  "description": "Sends a notification when power is high.",
  "mode": "single",
  "triggers": [{"type": "numeric_state", "entity_id": "sensor.power", "above": 3000}],
  "conditions": [{"type": "time", "after": "08:00:00", "before": "22:00:00"}],
  "action_sequence": [{"step_type": "service_call", "action": "notify.mobile_app_phone", "data": {"message": "Power is high"}}],
}

Example: wait_for_trigger with timeout and choose branching
input intent:
{
  "alias": "Appliance timeout",
  "description": "Waits for completion or notifies on timeout.",
  "mode": "single",
  "triggers": [{"type": "state", "entity_id": "sensor.appliance", "to": "running"}],
  "conditions": [],
  "action_sequence": [
    {
      "step_type": "wait_for_trigger",
      "wait_triggers": [{"type": "state", "entity_id": "sensor.appliance", "to": "idle"}],
      "timeout": "02:00:00"
    },
    {
      "step_type": "choose",
      "choose_options": [
        {
          "conditions": [{"type": "template", "value_template": "{{ not wait.completed }}"}],
          "sequence": [{"step_type": "service_call", "action": "notify.mobile_app_phone", "data": {"message": "Still running"}}]
        }
      ],
      "choose_default": [{"step_type": "service_call", "action": "switch.turn_off", "target_entity_ids": ["switch.example"]}]
    }
  ],
}

Example: multi-entity turn_on with colour data
input intent:
{
  "alias": "Warm lights",
  "description": "Sets a pair of lights to warm white.",
  "mode": "single",
  "triggers": [{"type": "time", "at": "18:30:00"}],
  "conditions": [],
  "action_sequence": [
    {
      "step_type": "service_call",
      "action": "light.turn_on",
      "target_entity_ids": ["light.left", "light.right"],
      "data": {"color_temp": 2700, "brightness_pct": 20}
    }
  ],
}

Example: repeat with flash
input intent:
{
  "alias": "Flash lights",
  "description": "Flashes lights twice.",
  "mode": "single",
  "triggers": [{"type": "event", "event_type": "example_event"}],
  "conditions": [],
  "action_sequence": [
    {
      "step_type": "repeat",
      "repeat_count": 2,
      "repeat_sequence": [
        {"step_type": "service_call", "action": "light.turn_on", "target_entity_ids": ["light.example"], "data": {"flash": "short"}},
        {"step_type": "delay", "delay": "00:00:01"}
      ]
    }
  ],
}

Example: delay then conditional notify
input intent:
{
  "alias": "Delayed notify",
  "description": "Waits then conditionally notifies.",
  "mode": "single",
  "triggers": [{"type": "state", "entity_id": "binary_sensor.example", "to": "on"}],
  "conditions": [],
  "action_sequence": [
    {"step_type": "delay", "delay": "00:05:00"},
    {
      "step_type": "if_then",
      "if_conditions": [{"type": "state", "entity_id": "binary_sensor.example", "state": "on"}],
      "then_sequence": [{"step_type": "service_call", "action": "notify.mobile_app_phone", "data": {"message": "Still on"}}]
    }
  ],
}
"""

from __future__ import annotations

from typing import Any

import yaml


def _compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values while preserving order."""
    return {
        key: value
        for key, value in data.items()
        if value is not None and value != [] and value != {}
    }


def _normalize_color_payload(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize light color payloads to Home Assistant-friendly values."""
    if not isinstance(data, dict):
        return data

    normalized = dict(data)
    color_temp = normalized.get("color_temp")
    if isinstance(color_temp, (int, float)) and color_temp > 1000:
        normalized["color_temp"] = round(1_000_000 / float(color_temp))

    kelvin = normalized.get("kelvin")
    if kelvin is not None and normalized.get("color_temp") is None:
        try:
            kelvin_value = float(kelvin)
        except (TypeError, ValueError):
            kelvin_value = 0.0
        if kelvin_value > 0:
            normalized["color_temp"] = round(1_000_000 / kelvin_value)
        normalized.pop("kelvin", None)

    color_name = str(normalized.get("color_name") or "").strip().lower()
    if color_name == "warm_white":
        normalized.pop("color_name", None)
        normalized.setdefault("color_temp", 370)

    return normalized


def _build_target(step: dict[str, Any]) -> dict[str, Any] | None:
    """Build a Home Assistant target block."""
    target = _compact_dict(
        {
            "entity_id": step.get("target_entity_ids"),
            "area_id": step.get("target_area_ids"),
            "device_id": step.get("target_device_ids"),
        }
    )
    return target or None


def _merge_extra(base: dict[str, Any], extra: Any) -> dict[str, Any]:
    """Merge an optional extra mapping into a base dict."""
    if not isinstance(extra, dict):
        return base
    merged = dict(base)
    for key, value in extra.items():
        if value is not None:
            merged[key] = value
    return merged


def _assemble_trigger(trigger: dict[str, Any]) -> dict[str, Any]:
    """Assemble one trigger block."""
    assembled = _compact_dict(
        {
            "trigger": trigger.get("type"),
            "entity_id": trigger.get("entity_id"),
            "to": trigger.get("to"),
            "from": trigger.get("from_state"),
            "for": trigger.get("for_duration"),
            "above": trigger.get("above"),
            "below": trigger.get("below"),
            "at": trigger.get("at"),
            "event": trigger.get("event"),
            "event_type": trigger.get("event_type"),
            "event_data": trigger.get("event_data"),
            "offset": trigger.get("offset"),
            "value_template": trigger.get("value_template"),
            "id": trigger.get("id"),
            "topic": trigger.get("topic"),
            "payload": trigger.get("payload"),
            "webhook_id": trigger.get("webhook_id"),
            "zone": trigger.get("zone"),
            "tag_id": trigger.get("tag_id"),
            "device_id": trigger.get("device_id"),
            "domain": trigger.get("domain"),
            "type": trigger.get("platform_type"),
        }
    )
    return _merge_extra(assembled, trigger.get("extra"))


def _assemble_condition(condition: dict[str, Any]) -> dict[str, Any]:
    """Assemble one condition block."""
    condition_type = str(condition.get("type") or "").strip()
    if condition_type in {"and", "or", "not"}:
        assembled = {
            "condition": condition_type,
            "conditions": [
                _assemble_condition(item)
                for item in condition.get("conditions", []) or []
            ],
        }
        return _merge_extra(_compact_dict(assembled), condition.get("extra"))

    assembled = _compact_dict(
        {
            "condition": condition_type,
            "entity_id": condition.get("entity_id"),
            "state": condition.get("state"),
            "above": condition.get("above"),
            "below": condition.get("below"),
            "after": condition.get("after"),
            "before": condition.get("before"),
            "weekday": condition.get("weekday"),
            "value_template": condition.get("value_template"),
            "event": condition.get("event"),
            "offset": condition.get("offset"),
            "zone": condition.get("zone"),
        }
    )
    return _merge_extra(assembled, condition.get("extra"))


def _assemble_choose_option(option: dict[str, Any]) -> dict[str, Any]:
    """Assemble a choose option block."""
    return {
        "conditions": [
            _assemble_condition(condition)
            for condition in option.get("conditions", []) or []
        ],
        "sequence": [
            _assemble_action_step(step)
            for step in option.get("sequence", []) or []
        ],
    }


def _assemble_action_step(step: dict[str, Any]) -> dict[str, Any]:
    """Assemble one script action step."""
    step_type = str(step.get("step_type") or "").strip()
    alias = step.get("alias")
    enabled = step.get("enabled")

    if step_type == "service_call":
        assembled = _compact_dict(
            {
                "action": step.get("action"),
                "target": _build_target(step),
                "data": _normalize_color_payload(step.get("data")),
            }
        )
    elif step_type == "delay":
        assembled = {"delay": step.get("delay")}
    elif step_type == "wait_for_trigger":
        timeout = step.get("timeout")
        assembled = _compact_dict(
            {
                "wait_for_trigger": [
                    _assemble_trigger(trigger)
                    for trigger in step.get("wait_triggers", []) or []
                ],
                "timeout": timeout,
                "continue_on_timeout": True if timeout else step.get("continue_on_timeout"),
            }
        )
    elif step_type == "wait_template":
        timeout = step.get("wait_timeout")
        assembled = _compact_dict(
            {
                "wait_template": step.get("wait_template"),
                "timeout": timeout,
                "continue_on_timeout": True if timeout else step.get("continue_on_timeout"),
            }
        )
    elif step_type == "choose":
        assembled = _compact_dict(
            {
                "choose": [
                    _assemble_choose_option(option)
                    for option in step.get("choose_options", []) or []
                ],
                "default": [
                    _assemble_action_step(item)
                    for item in step.get("choose_default", []) or []
                ],
            }
        )
    elif step_type == "if_then":
        assembled = _compact_dict(
            {
                "if": [
                    _assemble_condition(condition)
                    for condition in step.get("if_conditions", []) or []
                ],
                "then": [
                    _assemble_action_step(item)
                    for item in step.get("then_sequence", []) or []
                ],
                "else": [
                    _assemble_action_step(item)
                    for item in step.get("else_sequence", []) or []
                ],
            }
        )
    elif step_type == "repeat":
        repeat_body = _compact_dict(
            {
                "count": step.get("repeat_count"),
                "while": [
                    _assemble_condition(condition)
                    for condition in step.get("repeat_while", []) or []
                ],
                "until": [
                    _assemble_condition(condition)
                    for condition in step.get("repeat_until", []) or []
                ],
                "sequence": [
                    _assemble_action_step(item)
                    for item in step.get("repeat_sequence", []) or []
                ],
            }
        )
        assembled = {"repeat": repeat_body}
    elif step_type == "variables":
        assembled = {"variables": step.get("variables") or {}}
    elif step_type == "event":
        assembled = _compact_dict(
            {
                "event": step.get("event_type") or step.get("event"),
                "event_data": step.get("event_data"),
            }
        )
    elif step_type == "stop":
        assembled = _compact_dict(
            {
                "stop": step.get("stop_message"),
                "response_variable": step.get("response_variable"),
            }
        )
    elif step_type == "scene":
        assembled = {
            "action": "scene.turn_on",
            "target": {"entity_id": step.get("scene_entity_id")},
        }
    else:
        assembled = {"action": step.get("action")}

    if alias is not None:
        assembled["alias"] = alias
    if enabled is not None:
        assembled["enabled"] = enabled

    return _merge_extra(_compact_dict(assembled), step.get("extra"))


def assemble_yaml(intent: dict[str, Any]) -> str:
    """Assemble valid Home Assistant automation YAML from an intent dict."""
    automation = {
        "alias": str(intent.get("alias") or "").strip(),
        "description": str(intent.get("description") or "").strip(),
        "triggers": [
            _assemble_trigger(trigger)
            for trigger in intent.get("triggers", []) or []
        ],
        "conditions": [
            _assemble_condition(condition)
            for condition in intent.get("conditions", []) or []
        ],
        "actions": [
            _assemble_action_step(step)
            for step in intent.get("action_sequence", []) or []
        ],
        "mode": str(intent.get("mode") or "single").strip() or "single",
    }
    return yaml.safe_dump(
        automation,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
