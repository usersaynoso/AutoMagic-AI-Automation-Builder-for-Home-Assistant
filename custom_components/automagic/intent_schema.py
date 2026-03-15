"""Intent schema definitions and validation helpers for automation generation."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any


_ALLOWED_MODES = {"single", "restart", "queued", "parallel"}
_ALLOWED_TRIGGER_TYPES = {
    "calendar",
    "device",
    "event",
    "homeassistant",
    "mqtt",
    "numeric_state",
    "state",
    "sun",
    "tag",
    "template",
    "time",
    "webhook",
    "zone",
}
_ALLOWED_CONDITION_TYPES = {
    "and",
    "not",
    "numeric_state",
    "or",
    "state",
    "sun",
    "template",
    "time",
    "zone",
}
_ALLOWED_ACTION_STEP_TYPES = {
    "choose",
    "delay",
    "event",
    "if_then",
    "repeat",
    "scene",
    "service_call",
    "stop",
    "variables",
    "wait_for_trigger",
    "wait_template",
}


@dataclass
class TriggerIntent:
    """Structured trigger intent."""

    type: str
    entity_id: str | None = None
    to: str | None = None
    from_state: str | None = None
    for_duration: str | None = None
    above: float | str | None = None
    below: float | str | None = None
    at: str | None = None
    event: str | None = None
    event_type: str | None = None
    event_data: dict[str, Any] | None = None
    offset: str | None = None
    value_template: str | None = None
    id: str | None = None
    topic: str | None = None
    payload: str | None = None
    webhook_id: str | None = None
    zone: str | None = None
    tag_id: str | None = None
    device_id: str | None = None
    domain: str | None = None
    platform_type: str | None = None
    extra: dict[str, Any] | None = None


@dataclass
class ConditionIntent:
    """Structured condition intent."""

    type: str
    entity_id: str | None = None
    state: str | None = None
    above: float | str | None = None
    below: float | str | None = None
    after: str | None = None
    before: str | None = None
    weekday: list[str] | None = None
    value_template: str | None = None
    conditions: list["ConditionIntent"] | None = None
    event: str | None = None
    offset: str | None = None
    zone: str | None = None
    extra: dict[str, Any] | None = None


@dataclass
class ChooseOption:
    """Structured choose branch."""

    conditions: list[ConditionIntent]
    sequence: list["ActionStep"]


@dataclass
class ActionStep:
    """Structured action step."""

    step_type: str
    action: str | None = None
    target_entity_ids: list[str] | None = None
    target_area_ids: list[str] | None = None
    target_device_ids: list[str] | None = None
    data: dict[str, Any] | None = None
    delay: str | int | None = None
    wait_triggers: list[TriggerIntent] | None = None
    timeout: str | None = None
    continue_on_timeout: bool | None = None
    wait_template: str | None = None
    wait_timeout: str | None = None
    choose_options: list[ChooseOption] | None = None
    choose_default: list["ActionStep"] | None = None
    if_conditions: list[ConditionIntent] | None = None
    then_sequence: list["ActionStep"] | None = None
    else_sequence: list["ActionStep"] | None = None
    repeat_count: int | None = None
    repeat_while: list[ConditionIntent] | None = None
    repeat_until: list[ConditionIntent] | None = None
    repeat_sequence: list["ActionStep"] | None = None
    variables: dict[str, Any] | None = None
    event: str | None = None
    event_type: str | None = None
    event_data: dict[str, Any] | None = None
    stop_message: str | None = None
    response_variable: str | None = None
    scene_entity_id: str | None = None
    alias: str | None = None
    enabled: bool | None = None
    extra: dict[str, Any] | None = None


@dataclass
class AutomationIntent:
    """Top-level automation intent."""

    alias: str
    description: str
    mode: str
    triggers: list[TriggerIntent]
    conditions: list[ConditionIntent] = field(default_factory=list)
    action_sequence: list[ActionStep] = field(default_factory=list)


_INTENT_JSON_SCHEMA_DICT: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "AutomationIntentPayload",
    "type": "object",
    "required": ["intent", "summary"],
    "properties": {
        "intent": {"$ref": "#/$defs/AutomationIntent"},
        "summary": {"type": "string"},
        "needs_clarification": {"type": "boolean"},
        "clarifying_questions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
    },
    "$defs": {
        "AutomationIntent": {
            "type": "object",
            "required": [
                "alias",
                "description",
                "mode",
                "triggers",
                "conditions",
                "action_sequence",
            ],
            "properties": {
                "alias": {"type": "string"},
                "description": {"type": "string"},
                "mode": {"type": "string", "enum": sorted(_ALLOWED_MODES)},
                "triggers": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/TriggerIntent"},
                },
                "conditions": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/ConditionIntent"},
                },
                "action_sequence": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/ActionStep"},
                },
            },
            "additionalProperties": True,
        },
        "TriggerIntent": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"type": "string", "enum": sorted(_ALLOWED_TRIGGER_TYPES)},
                "entity_id": {"type": ["string", "null"]},
                "to": {"type": ["string", "null"]},
                "from_state": {"type": ["string", "null"]},
                "for_duration": {"type": ["string", "null"]},
                "above": {"type": ["number", "string", "null"]},
                "below": {"type": ["number", "string", "null"]},
                "at": {"type": ["string", "null"]},
                "event": {"type": ["string", "null"]},
                "event_type": {"type": ["string", "null"]},
                "event_data": {"type": ["object", "null"]},
                "offset": {"type": ["string", "null"]},
                "value_template": {"type": ["string", "null"]},
                "id": {"type": ["string", "null"]},
                "topic": {"type": ["string", "null"]},
                "payload": {"type": ["string", "null"]},
                "webhook_id": {"type": ["string", "null"]},
                "zone": {"type": ["string", "null"]},
                "tag_id": {"type": ["string", "null"]},
                "device_id": {"type": ["string", "null"]},
                "domain": {"type": ["string", "null"]},
                "platform_type": {"type": ["string", "null"]},
                "extra": {"type": ["object", "null"]},
            },
            "additionalProperties": True,
        },
        "ConditionIntent": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"type": "string", "enum": sorted(_ALLOWED_CONDITION_TYPES)},
                "entity_id": {"type": ["string", "null"]},
                "state": {"type": ["string", "null"]},
                "above": {"type": ["number", "string", "null"]},
                "below": {"type": ["number", "string", "null"]},
                "after": {"type": ["string", "null"]},
                "before": {"type": ["string", "null"]},
                "weekday": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "value_template": {"type": ["string", "null"]},
                "conditions": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ConditionIntent"},
                },
                "event": {"type": ["string", "null"]},
                "offset": {"type": ["string", "null"]},
                "zone": {"type": ["string", "null"]},
                "extra": {"type": ["object", "null"]},
            },
            "additionalProperties": True,
        },
        "ChooseOption": {
            "type": "object",
            "required": ["conditions", "sequence"],
            "properties": {
                "conditions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/ConditionIntent"},
                },
                "sequence": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/ActionStep"},
                },
            },
            "additionalProperties": True,
        },
        "ActionStep": {
            "type": "object",
            "required": ["step_type"],
            "properties": {
                "step_type": {
                    "type": "string",
                    "enum": sorted(_ALLOWED_ACTION_STEP_TYPES),
                },
                "action": {"type": ["string", "null"]},
                "target_entity_ids": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "target_area_ids": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "target_device_ids": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "data": {"type": ["object", "null"]},
                "delay": {"type": ["string", "integer", "null"]},
                "wait_triggers": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/TriggerIntent"},
                },
                "timeout": {"type": ["string", "null"]},
                "continue_on_timeout": {"type": ["boolean", "null"]},
                "wait_template": {"type": ["string", "null"]},
                "wait_timeout": {"type": ["string", "null"]},
                "choose_options": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ChooseOption"},
                },
                "choose_default": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ActionStep"},
                },
                "if_conditions": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ConditionIntent"},
                },
                "then_sequence": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ActionStep"},
                },
                "else_sequence": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ActionStep"},
                },
                "repeat_count": {"type": ["integer", "null"]},
                "repeat_while": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ConditionIntent"},
                },
                "repeat_until": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ConditionIntent"},
                },
                "repeat_sequence": {
                    "type": ["array", "null"],
                    "items": {"$ref": "#/$defs/ActionStep"},
                },
                "variables": {"type": ["object", "null"]},
                "event": {"type": ["string", "null"]},
                "event_type": {"type": ["string", "null"]},
                "event_data": {"type": ["object", "null"]},
                "stop_message": {"type": ["string", "null"]},
                "response_variable": {"type": ["string", "null"]},
                "scene_entity_id": {"type": ["string", "null"]},
                "alias": {"type": ["string", "null"]},
                "enabled": {"type": ["boolean", "null"]},
                "extra": {"type": ["object", "null"]},
            },
            "additionalProperties": True,
        },
    },
}

INTENT_JSON_SCHEMA = json.dumps(_INTENT_JSON_SCHEMA_DICT, indent=2, sort_keys=True)


def _non_empty_string(value: Any) -> bool:
    """Return True when value is a non-empty string."""
    return isinstance(value, str) and bool(value.strip())


def _is_list_of_strings(value: Any) -> bool:
    """Return True when the value is a list of non-empty strings."""
    return isinstance(value, list) and all(_non_empty_string(item) for item in value)


def _validate_trigger(
    trigger: Any,
    path: str,
    issues: list[str],
) -> None:
    """Validate a trigger intent."""
    if not isinstance(trigger, dict):
        issues.append(f"{path} must be an object.")
        return

    trigger_type = str(trigger.get("type") or "").strip()
    if trigger_type not in _ALLOWED_TRIGGER_TYPES:
        issues.append(
            f"{path}.type must be one of {', '.join(sorted(_ALLOWED_TRIGGER_TYPES))}."
        )
        return

    if trigger_type in {"state", "numeric_state", "zone", "calendar"} and not _non_empty_string(
        trigger.get("entity_id")
    ):
        issues.append(f"{path}.entity_id is required for {trigger_type} triggers.")

    if trigger_type == "numeric_state" and trigger.get("above") is None and trigger.get("below") is None:
        issues.append(f"{path} must define above or below for a numeric_state trigger.")
    if trigger_type == "time" and not _non_empty_string(trigger.get("at")):
        issues.append(f"{path}.at is required for time triggers.")
    if trigger_type == "sun" and str(trigger.get("event") or "").strip() not in {"sunrise", "sunset"}:
        issues.append(f"{path}.event must be sunrise or sunset for sun triggers.")
    if trigger_type == "template" and not _non_empty_string(trigger.get("value_template")):
        issues.append(f"{path}.value_template is required for template triggers.")
    if trigger_type == "event" and not (
        _non_empty_string(trigger.get("event_type"))
        or _non_empty_string(trigger.get("event"))
    ):
        issues.append(f"{path}.event_type is required for event triggers.")
    if trigger_type == "webhook" and not _non_empty_string(trigger.get("webhook_id")):
        issues.append(f"{path}.webhook_id is required for webhook triggers.")
    if trigger_type == "mqtt" and not _non_empty_string(trigger.get("topic")):
        issues.append(f"{path}.topic is required for mqtt triggers.")
    if trigger_type == "tag" and not _non_empty_string(trigger.get("tag_id")):
        issues.append(f"{path}.tag_id is required for tag triggers.")


def _validate_condition(
    condition: Any,
    path: str,
    issues: list[str],
) -> None:
    """Validate a condition intent."""
    if not isinstance(condition, dict):
        issues.append(f"{path} must be an object.")
        return

    condition_type = str(condition.get("type") or "").strip()
    if condition_type not in _ALLOWED_CONDITION_TYPES:
        issues.append(
            f"{path}.type must be one of {', '.join(sorted(_ALLOWED_CONDITION_TYPES))}."
        )
        return

    if condition_type == "state":
        if not _non_empty_string(condition.get("entity_id")):
            issues.append(f"{path}.entity_id is required for state conditions.")
        if not _non_empty_string(condition.get("state")):
            issues.append(f"{path}.state is required for state conditions.")
    elif condition_type == "numeric_state":
        if not _non_empty_string(condition.get("entity_id")):
            issues.append(f"{path}.entity_id is required for numeric_state conditions.")
        if condition.get("above") is None and condition.get("below") is None:
            issues.append(f"{path} must define above or below for a numeric_state condition.")
    elif condition_type == "time":
        if (
            not _non_empty_string(condition.get("after"))
            and not _non_empty_string(condition.get("before"))
            and not isinstance(condition.get("weekday"), list)
        ):
            issues.append(
                f"{path} must define after, before, or weekday for a time condition."
            )
    elif condition_type == "template":
        if not _non_empty_string(condition.get("value_template")):
            issues.append(f"{path}.value_template is required for template conditions.")
    elif condition_type in {"and", "or", "not"}:
        nested = condition.get("conditions")
        if not isinstance(nested, list) or not nested:
            issues.append(f"{path}.conditions must be a non-empty list for {condition_type} conditions.")
        else:
            for index, nested_condition in enumerate(nested):
                _validate_condition(
                    nested_condition,
                    f"{path}.conditions[{index}]",
                    issues,
                )
    elif condition_type == "zone" and not _non_empty_string(condition.get("entity_id")):
        issues.append(f"{path}.entity_id is required for zone conditions.")


def _validate_action_step(
    step: Any,
    path: str,
    issues: list[str],
) -> None:
    """Validate an action step."""
    if not isinstance(step, dict):
        issues.append(f"{path} must be an object.")
        return

    step_type = str(step.get("step_type") or "").strip()
    if step_type not in _ALLOWED_ACTION_STEP_TYPES:
        issues.append(
            f"{path}.step_type must be one of {', '.join(sorted(_ALLOWED_ACTION_STEP_TYPES))}."
        )
        return

    if step_type == "service_call":
        if not _non_empty_string(step.get("action")):
            issues.append(f"{path}.action is required for service_call steps.")
    elif step_type == "delay":
        if step.get("delay") in (None, "", []):
            issues.append(f"{path}.delay is required for delay steps.")
    elif step_type == "wait_for_trigger":
        wait_triggers = step.get("wait_triggers")
        if not isinstance(wait_triggers, list) or not wait_triggers:
            issues.append(f"{path}.wait_triggers must be a non-empty list.")
        else:
            for index, trigger in enumerate(wait_triggers):
                _validate_trigger(trigger, f"{path}.wait_triggers[{index}]", issues)
    elif step_type == "wait_template":
        if not _non_empty_string(step.get("wait_template")):
            issues.append(f"{path}.wait_template is required for wait_template steps.")
    elif step_type == "choose":
        choose_options = step.get("choose_options")
        if not isinstance(choose_options, list) or not choose_options:
            issues.append(f"{path}.choose_options must be a non-empty list.")
        else:
            for option_index, option in enumerate(choose_options):
                if not isinstance(option, dict):
                    issues.append(f"{path}.choose_options[{option_index}] must be an object.")
                    continue
                conditions = option.get("conditions")
                sequence = option.get("sequence")
                if not isinstance(conditions, list) or not conditions:
                    issues.append(
                        f"{path}.choose_options[{option_index}].conditions must be a non-empty list."
                    )
                else:
                    for condition_index, condition in enumerate(conditions):
                        _validate_condition(
                            condition,
                            f"{path}.choose_options[{option_index}].conditions[{condition_index}]",
                            issues,
                        )
                if not isinstance(sequence, list) or not sequence:
                    issues.append(
                        f"{path}.choose_options[{option_index}].sequence must be a non-empty list."
                    )
                else:
                    for sequence_index, nested_step in enumerate(sequence):
                        _validate_action_step(
                            nested_step,
                            f"{path}.choose_options[{option_index}].sequence[{sequence_index}]",
                            issues,
                        )
        default_sequence = step.get("choose_default")
        if default_sequence is not None and not isinstance(default_sequence, list):
            issues.append(f"{path}.choose_default must be a list when provided.")
    elif step_type == "if_then":
        if_conditions = step.get("if_conditions")
        then_sequence = step.get("then_sequence")
        if not isinstance(if_conditions, list) or not if_conditions:
            issues.append(f"{path}.if_conditions must be a non-empty list.")
        else:
            for index, condition in enumerate(if_conditions):
                _validate_condition(condition, f"{path}.if_conditions[{index}]", issues)
        if not isinstance(then_sequence, list) or not then_sequence:
            issues.append(f"{path}.then_sequence must be a non-empty list.")
        else:
            for index, nested_step in enumerate(then_sequence):
                _validate_action_step(
                    nested_step,
                    f"{path}.then_sequence[{index}]",
                    issues,
                )
        else_sequence = step.get("else_sequence")
        if else_sequence is not None and not isinstance(else_sequence, list):
            issues.append(f"{path}.else_sequence must be a list when provided.")
    elif step_type == "repeat":
        if (
            step.get("repeat_count") is None
            and not step.get("repeat_while")
            and not step.get("repeat_until")
        ):
            issues.append(
                f"{path} must define repeat_count, repeat_while, or repeat_until for repeat steps."
            )
        repeat_sequence = step.get("repeat_sequence")
        if not isinstance(repeat_sequence, list) or not repeat_sequence:
            issues.append(f"{path}.repeat_sequence must be a non-empty list.")
        else:
            for index, nested_step in enumerate(repeat_sequence):
                _validate_action_step(
                    nested_step,
                    f"{path}.repeat_sequence[{index}]",
                    issues,
                )
    elif step_type == "variables":
        if not isinstance(step.get("variables"), dict) or not step.get("variables"):
            issues.append(f"{path}.variables must be a non-empty object.")
    elif step_type == "event":
        if not (
            _non_empty_string(step.get("event_type"))
            or _non_empty_string(step.get("event"))
        ):
            issues.append(f"{path}.event_type is required for event steps.")
    elif step_type == "stop":
        if not _non_empty_string(step.get("stop_message")):
            issues.append(f"{path}.stop_message is required for stop steps.")
    elif step_type == "scene":
        if not _non_empty_string(step.get("scene_entity_id")):
            issues.append(f"{path}.scene_entity_id is required for scene steps.")

    for list_key in ("target_entity_ids", "target_area_ids", "target_device_ids"):
        list_value = step.get(list_key)
        if list_value is not None and not _is_list_of_strings(list_value):
            issues.append(f"{path}.{list_key} must be a list of strings when provided.")


def validate_intent(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a parsed automation intent."""
    issues: list[str] = []
    if not isinstance(data, dict):
        return False, ["Intent must be a JSON object."]

    if not _non_empty_string(data.get("alias")):
        issues.append("intent.alias is required.")
    if not _non_empty_string(data.get("description")):
        issues.append("intent.description is required.")

    mode = str(data.get("mode") or "").strip()
    if mode not in _ALLOWED_MODES:
        issues.append(
            f"intent.mode must be one of {', '.join(sorted(_ALLOWED_MODES))}."
        )

    triggers = data.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        issues.append("intent.triggers must be a non-empty list.")
    else:
        for index, trigger in enumerate(triggers):
            _validate_trigger(trigger, f"intent.triggers[{index}]", issues)

    conditions = data.get("conditions")
    if conditions is None:
        issues.append("intent.conditions is required.")
    elif not isinstance(conditions, list):
        issues.append("intent.conditions must be a list.")
    else:
        for index, condition in enumerate(conditions):
            _validate_condition(condition, f"intent.conditions[{index}]", issues)

    action_sequence = data.get("action_sequence")
    if not isinstance(action_sequence, list) or not action_sequence:
        issues.append("intent.action_sequence must be a non-empty list.")
    else:
        for index, step in enumerate(action_sequence):
            _validate_action_step(step, f"intent.action_sequence[{index}]", issues)

    deduped = list(dict.fromkeys(issue.strip() for issue in issues if issue.strip()))
    return not deduped, deduped


def collect_intent_entity_ids(intent: dict[str, Any]) -> set[str]:
    """Collect entity references from an intent tree."""
    entity_ids: set[str] = set()

    def _walk_trigger(trigger: Any) -> None:
        if not isinstance(trigger, dict):
            return
        entity_id = str(trigger.get("entity_id") or "").strip()
        if entity_id:
            entity_ids.add(entity_id)
        for value in trigger.values():
            if isinstance(value, dict):
                _walk_mapping(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _walk_mapping(item)

    def _walk_condition(condition: Any) -> None:
        if not isinstance(condition, dict):
            return
        entity_id = str(condition.get("entity_id") or "").strip()
        if entity_id:
            entity_ids.add(entity_id)
        nested = condition.get("conditions")
        if isinstance(nested, list):
            for item in nested:
                _walk_condition(item)

    def _walk_action(step: Any) -> None:
        if not isinstance(step, dict):
            return
        for key in ("target_entity_ids",):
            value = step.get(key)
            if isinstance(value, list):
                for item in value:
                    entity_id = str(item or "").strip()
                    if entity_id:
                        entity_ids.add(entity_id)
        scene_entity_id = str(step.get("scene_entity_id") or "").strip()
        if scene_entity_id:
            entity_ids.add(scene_entity_id)
        wait_triggers = step.get("wait_triggers")
        if isinstance(wait_triggers, list):
            for trigger in wait_triggers:
                _walk_trigger(trigger)
        choose_options = step.get("choose_options")
        if isinstance(choose_options, list):
            for option in choose_options:
                if not isinstance(option, dict):
                    continue
                for condition in option.get("conditions", []) or []:
                    _walk_condition(condition)
                for nested_step in option.get("sequence", []) or []:
                    _walk_action(nested_step)
        for key in ("choose_default", "then_sequence", "else_sequence", "repeat_sequence"):
            nested_steps = step.get(key)
            if isinstance(nested_steps, list):
                for nested_step in nested_steps:
                    _walk_action(nested_step)
        for key in ("if_conditions", "repeat_while", "repeat_until"):
            nested_conditions = step.get(key)
            if isinstance(nested_conditions, list):
                for condition in nested_conditions:
                    _walk_condition(condition)

    def _walk_mapping(value: Any) -> None:
        if not isinstance(value, dict):
            return
        if "step_type" in value:
            _walk_action(value)
        elif "type" in value and any(
            key in value for key in ("to", "from_state", "for_duration", "at", "value_template")
        ):
            _walk_trigger(value)
        elif "type" in value:
            _walk_condition(value)
        else:
            for nested in value.values():
                if isinstance(nested, dict):
                    _walk_mapping(nested)
                elif isinstance(nested, list):
                    for item in nested:
                        if isinstance(item, dict):
                            _walk_mapping(item)

    for trigger in intent.get("triggers", []) or []:
        _walk_trigger(trigger)
    for condition in intent.get("conditions", []) or []:
        _walk_condition(condition)
    for step in intent.get("action_sequence", []) or []:
        _walk_action(step)

    return entity_ids
