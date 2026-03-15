"""Programmatic YAML autofix helpers for common Home Assistant automation issues."""

from __future__ import annotations

import copy
import re
from typing import Any

import yaml

from .entity_collector import (
    build_entity_resolution_map,
    extract_explicit_state_guards,
    extract_negated_state_guards,
)
from .llm_client import _normalize_automation_yaml_text


_ACTION_FORMAT_RE = re.compile(r"^[a-z_]+\.[a-z_0-9]+$")
_TIMEOUT_DURATION_RE = re.compile(
    r"\b(?:after|within|for)\s+(\d+)\s*(hour|hours|hr|hrs|minute|minutes|min|mins)\b",
    re.IGNORECASE,
)
_BRIGHTNESS_RE = re.compile(
    r"\b(?:brightness\s*(?:of|at)?\s*|at\s*)(\d{1,3})\s*%?\s*brightness\b|\bbrightness\s*(\d{1,3})\s*%?\b",
    re.IGNORECASE,
)
_KELVIN_RE = re.compile(r"\b(\d{4})\s*k\b", re.IGNORECASE)
_WARM_WHITE_RE = re.compile(r"\bwarm white\b|\bwarm light\b", re.IGNORECASE)
_COLOR_NAME_UNDERSCORE_RE = re.compile(r"^[a-z0-9]+_[a-z0-9_]+$", re.IGNORECASE)
_STILL_RUNNING_TIMEOUT_RE = re.compile(
    r"\b(still running|still cleaning|still active|hasn.t finished|not finished|might be stuck|stuck)\b",
    re.IGNORECASE,
)


def _compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Drop empty values while preserving insertion order."""
    return {
        key: value
        for key, value in data.items()
        if value is not None and value != [] and value != {}
    }


def _extract_brightness_pct(prompt_text: str) -> int | None:
    """Extract a brightness percentage from prompt text."""
    match = _BRIGHTNESS_RE.search(str(prompt_text or ""))
    if not match:
        return None
    raw = match.group(1) or match.group(2)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return min(100, max(1, value))


def _extract_color_temp_mireds(prompt_text: str) -> int | None:
    """Extract a preferred color temperature from prompt text."""
    kelvin_match = _KELVIN_RE.search(str(prompt_text or ""))
    if kelvin_match:
        try:
            kelvin = int(kelvin_match.group(1))
        except ValueError:
            kelvin = 0
        if kelvin > 0:
            return round(1_000_000 / kelvin)
    if _WARM_WHITE_RE.search(str(prompt_text or "")):
        return 370
    return None


def _extract_timeout(prompt_text: str) -> str | None:
    """Extract a timeout duration in HH:MM:SS format from prompt text."""
    match = _TIMEOUT_DURATION_RE.search(str(prompt_text or ""))
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith("hour") or unit.startswith("hr"):
        hours = amount
        minutes = 0
    else:
        hours, minutes = divmod(amount, 60)
    return f"{hours:02d}:{minutes:02d}:00"


def _as_list(value: Any) -> list[Any]:
    """Return value as a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _extract_action_target_ids(action_item: dict[str, Any]) -> list[str]:
    """Extract target entity ids from an action mapping."""
    target = action_item.get("target")
    if not isinstance(target, dict):
        return []
    value = target.get("entity_id")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _set_action_target_ids(action_item: dict[str, Any], entity_ids: list[str]) -> None:
    """Set an action target block from entity ids."""
    cleaned = [entity_id for entity_id in entity_ids if entity_id]
    if not cleaned:
        return
    action_item.setdefault("target", {})
    if len(cleaned) == 1:
        action_item["target"]["entity_id"] = cleaned[0]
    else:
        action_item["target"]["entity_id"] = cleaned


def _normalize_color_payload(data: dict[str, Any], fixes: list[str]) -> dict[str, Any]:
    """Normalize light color payload values."""
    normalized = dict(data)
    color_temp = normalized.get("color_temp")
    try:
        numeric_color_temp = float(color_temp)
    except (TypeError, ValueError):
        numeric_color_temp = 0.0
    if numeric_color_temp > 1000:
        mireds = round(1_000_000 / numeric_color_temp)
        normalized["color_temp"] = mireds
        fixes.append(
            f"Converted color_temp from {int(numeric_color_temp)}K to {mireds} mireds"
        )

    color_name = str(normalized.get("color_name") or "").strip()
    if color_name and _COLOR_NAME_UNDERSCORE_RE.match(color_name):
        normalized.pop("color_name", None)
        normalized.setdefault("color_temp", 370)
        fixes.append(
            f"Replaced unsupported color_name {color_name!r} with color_temp: 370"
        )

    kelvin = normalized.pop("kelvin", None)
    if kelvin is not None and normalized.get("color_temp") is None:
        try:
            kelvin_value = float(kelvin)
        except (TypeError, ValueError):
            kelvin_value = 0.0
        if kelvin_value > 0:
            mireds = round(1_000_000 / kelvin_value)
            normalized["color_temp"] = mireds
            fixes.append(
                f"Converted kelvin {int(kelvin_value)} to color_temp: {mireds}"
            )

    return normalized


def _fix_trigger_mapping(trigger: dict[str, Any], fixes: list[str]) -> None:
    """Normalize one trigger mapping in place."""
    if "platform" in trigger and "trigger" not in trigger:
        trigger["trigger"] = trigger.pop("platform")
        fixes.append("Renamed platform: to trigger: in a trigger block")

    nested_trigger = trigger.get("trigger")
    if isinstance(nested_trigger, dict):
        nested = dict(nested_trigger)
        trigger_type = nested.pop("trigger", None) or nested.pop("platform", None)
        if isinstance(trigger_type, str) and trigger_type:
            trigger["trigger"] = trigger_type
            for key, value in nested.items():
                trigger.setdefault(key, value)
            fixes.append("Flattened a nested trigger mapping into trigger: syntax")


def _condition_from_action(action_item: dict[str, Any]) -> dict[str, Any]:
    """Extract a condition mapping from a bare action-list condition."""
    condition = {
        "condition": action_item.get("condition"),
        "entity_id": action_item.get("entity_id"),
        "state": action_item.get("state"),
        "above": action_item.get("above"),
        "below": action_item.get("below"),
        "weekday": action_item.get("weekday"),
        "after": action_item.get("after"),
        "before": action_item.get("before"),
        "value_template": action_item.get("value_template"),
        "conditions": action_item.get("conditions"),
    }
    return _compact_dict(condition)


def _action_has_wait_completed_choose(action_item: dict[str, Any]) -> bool:
    """Return True when a choose block branches on wait.completed."""
    choose = action_item.get("choose")
    if not isinstance(choose, list):
        return False
    for option in choose:
        if not isinstance(option, dict):
            continue
        for condition in option.get("conditions", []) or []:
            if not isinstance(condition, dict):
                continue
            if (
                condition.get("condition") == "template"
                and "wait.completed" in str(condition.get("value_template") or "")
            ):
                return True
    return False


def _inject_colour_data_if_needed(
    action_item: dict[str, Any],
    prompt_text: str,
    entity_map: dict[str, dict[str, Any]],
    fixes: list[str],
) -> None:
    """Inject missing colour data for light actions when the prompt requires it."""
    if str(action_item.get("action") or "") != "light.turn_on":
        return

    target_ids = set(_extract_action_target_ids(action_item))
    if not target_ids:
        return

    requested_entities: set[str] = set()
    color_temp = _extract_color_temp_mireds(prompt_text)
    brightness_pct = _extract_brightness_pct(prompt_text)
    for payload in entity_map.values():
        colour_request = payload.get("colour_request") or {}
        role = str(payload.get("role") or "").strip().lower()
        if role != "action_target":
            continue
        payload_targets = {
            str(entity_id).strip()
            for entity_id in payload.get("entity_ids", []) or []
            if str(entity_id).strip()
        }
        if not target_ids & payload_targets:
            continue
        requested_entities.update(target_ids & payload_targets)
        if color_temp is None and colour_request.get("color_temp"):
            color_temp = int(colour_request["color_temp"])
        if brightness_pct is None and colour_request.get("brightness_pct"):
            brightness_pct = int(colour_request["brightness_pct"])

    if not requested_entities:
        return

    data = action_item.get("data")
    if not isinstance(data, dict):
        data = {}
        action_item["data"] = data

    added_parts: list[str] = []
    if (
        color_temp is not None
        and all(key not in data for key in ("color_temp", "color_name", "rgb_color", "xy_color", "kelvin"))
    ):
        data["color_temp"] = color_temp
        added_parts.append(f"color_temp: {color_temp}")
    if brightness_pct is not None and "brightness_pct" not in data:
        data["brightness_pct"] = brightness_pct
        added_parts.append(f"brightness_pct: {brightness_pct}")

    if added_parts:
        fixes.append(
            "Injected missing light data for "
            + ", ".join(sorted(requested_entities))
            + " with "
            + ", ".join(added_parts)
        )

    action_item["data"] = _normalize_color_payload(action_item["data"], fixes)


def _fix_action_item(
    action_item: dict[str, Any],
    prompt_text: str,
    entity_map: dict[str, dict[str, Any]],
    fixes: list[str],
) -> dict[str, Any]:
    """Fix one action item in place and recurse into nested sequences."""
    if "service" in action_item and "action" not in action_item:
        action_item["action"] = action_item.pop("service")
        fixes.append("Renamed service: to action: in an action step")

    action_name = str(action_item.get("action") or "").strip()
    if action_name == "delay":
        duration = None
        data = action_item.get("data")
        if isinstance(data, dict):
            duration = data.get("duration") or data.get("delay")
        duration = duration or action_item.get("duration")
        if duration:
            preserved: dict[str, Any] = {"delay": duration}
            if action_item.get("alias") is not None:
                preserved["alias"] = action_item["alias"]
            if action_item.get("enabled") is not None:
                preserved["enabled"] = action_item["enabled"]
            if isinstance(action_item.get("extra"), dict):
                preserved.update(action_item["extra"])
            fixes.append("Converted action: delay into a delay: step")
            return preserved

    if action_name and not _ACTION_FORMAT_RE.match(action_name):
        parts = action_name.split(".")
        if len(parts) >= 3 and re.fullmatch(r"[a-z_]+", parts[0]):
            entity_id = f"{parts[0]}.{ '_'.join(parts[1:-1]) }"
            new_action = f"{parts[0]}.{parts[-1]}"
            _set_action_target_ids(action_item, [entity_id, *_extract_action_target_ids(action_item)])
            action_item["action"] = new_action
            fixes.append(
                f"Moved embedded entity reference {entity_id} out of action: into target.entity_id"
            )

    action_name = str(action_item.get("action") or "").strip()
    if action_name in {"scene.turn_all_off", "scene.turn_all_on"}:
        action_item["action"] = "scene.turn_on"
        if "entity_id" in action_item and "target" not in action_item:
            _set_action_target_ids(action_item, _as_list(action_item.pop("entity_id")))
        fixes.append(
            f"Replaced invalid {action_name} with scene.turn_on"
        )

    if action_name.startswith("notify.") and "message" in action_item:
        message = action_item.pop("message")
        action_item.setdefault("data", {})
        if "message" not in action_item["data"]:
            action_item["data"]["message"] = message
            fixes.append("Wrapped notify message inside data.message")

    if isinstance(action_item.get("data"), dict):
        action_item["data"] = _normalize_color_payload(action_item["data"], fixes)

    _inject_colour_data_if_needed(action_item, prompt_text, entity_map, fixes)

    if isinstance(action_item.get("wait_for_trigger"), list):
        for trigger in action_item["wait_for_trigger"]:
            if isinstance(trigger, dict):
                _fix_trigger_mapping(trigger, fixes)

    for key in ("sequence", "default", "then", "else"):
        nested = action_item.get(key)
        if isinstance(nested, list):
            action_item[key] = _fix_action_list(
                nested,
                prompt_text,
                entity_map,
                fixes,
                fallback_conditions=None,
            )

    choose = action_item.get("choose")
    if isinstance(choose, list):
        fixed_choose = []
        for option in choose:
            if not isinstance(option, dict):
                fixed_choose.append(option)
                continue
            fixed_option = dict(option)
            if isinstance(fixed_option.get("sequence"), list):
                fixed_option["sequence"] = _fix_action_list(
                    fixed_option["sequence"],
                    prompt_text,
                    entity_map,
                    fixes,
                    fallback_conditions=None,
                )
            fixed_choose.append(fixed_option)
        action_item["choose"] = fixed_choose

    repeat = action_item.get("repeat")
    if isinstance(repeat, dict) and isinstance(repeat.get("sequence"), list):
        repeat["sequence"] = _fix_action_list(
            repeat["sequence"],
            prompt_text,
            entity_map,
            fixes,
            fallback_conditions=None,
        )

    return action_item


def _fix_action_list(
    actions: list[Any],
    prompt_text: str,
    entity_map: dict[str, dict[str, Any]],
    fixes: list[str],
    fallback_conditions: list[dict[str, Any]] | None,
) -> list[Any]:
    """Fix an action list in place."""
    timeout_value = _extract_timeout(prompt_text)
    fixed_actions: list[Any] = []
    index = 0
    while index < len(actions):
        raw_item = actions[index]
        if not isinstance(raw_item, dict):
            fixed_actions.append(raw_item)
            index += 1
            continue

        action_item = _fix_action_item(dict(raw_item), prompt_text, entity_map, fixes)

        if "condition" in action_item and "action" not in action_item and "choose" not in action_item:
            condition_entry = _condition_from_action(action_item)
            if index + 1 < len(actions):
                next_action = _fix_action_item(
                    dict(actions[index + 1]),
                    prompt_text,
                    entity_map,
                    fixes,
                )
                fixed_actions.append(
                    {
                        "choose": [
                            {
                                "conditions": [condition_entry],
                                "sequence": [next_action],
                            }
                        ]
                    }
                )
                fixes.append("Wrapped a bare action-list condition in a choose block")
                index += 2
                continue
            if fallback_conditions is not None:
                fallback_conditions.append(condition_entry)
                fixes.append("Moved a trailing bare action-list condition to top-level conditions")
            index += 1
            continue

        if isinstance(action_item.get("wait_for_trigger"), list) and timeout_value:
            if "timeout" not in action_item:
                action_item["timeout"] = timeout_value
                action_item["continue_on_timeout"] = True
                fixes.append(f"Injected wait_for_trigger timeout {timeout_value}")
            elif "continue_on_timeout" not in action_item:
                action_item["continue_on_timeout"] = True
                fixes.append("Added continue_on_timeout: true to wait_for_trigger")

            next_item = actions[index + 1] if index + 1 < len(actions) else None
            if (
                isinstance(next_item, dict)
                and str(next_item.get("action") or "").startswith("notify.")
                and not _action_has_wait_completed_choose(next_item)
                and _STILL_RUNNING_TIMEOUT_RE.search(prompt_text)
            ):
                notify_action = _fix_action_item(
                    dict(next_item),
                    prompt_text,
                    entity_map,
                    fixes,
                )
                fixed_actions.append(action_item)
                fixed_actions.append(
                    {
                        "choose": [
                            {
                                "conditions": [
                                    {
                                        "condition": "template",
                                        "value_template": "{{ not wait.completed }}",
                                    }
                                ],
                                "sequence": [notify_action],
                            }
                        ]
                    }
                )
                fixes.append(
                    "Wrapped the timeout notification in a choose block gated by wait.completed"
                )
                index += 2
                continue

        fixed_actions.append(action_item)
        index += 1

    return fixed_actions


def _condition_exists(conditions: list[dict[str, Any]], target: dict[str, Any]) -> bool:
    """Return True when a target condition already exists."""
    for condition in conditions:
        if condition == target:
            return True
        if not isinstance(condition, dict):
            continue
        if (
            condition.get("condition") == target.get("condition")
            and condition.get("entity_id") == target.get("entity_id")
            and condition.get("state") == target.get("state")
        ):
            return True
        if (
            condition.get("condition") == "not"
            and target.get("condition") == "not"
            and condition.get("conditions") == target.get("conditions")
        ):
            return True
    return False


def _ensure_guard_conditions(
    parsed: dict[str, Any],
    prompt_text: str,
    entities: list[dict[str, Any]],
    fixes: list[str],
) -> None:
    """Ensure prompt-implied guards exist in top-level conditions."""
    conditions = parsed.setdefault("conditions", [])
    if not isinstance(conditions, list):
        parsed["conditions"] = []
        conditions = parsed["conditions"]

    for guard in extract_explicit_state_guards(prompt_text, entities):
        entity_id = str(guard.get("entity_id") or "").strip()
        blocked_state = str(guard.get("blocked_state") or "").strip()
        required_state = str(guard.get("required_state") or "").strip()
        if not entity_id:
            continue
        if required_state:
            condition = {
                "condition": "state",
                "entity_id": entity_id,
                "state": required_state,
            }
            if not _condition_exists(conditions, condition):
                conditions.append(condition)
                fixes.append(
                    f"Added missing top-level guard requiring {entity_id} to be {required_state}"
                )
        elif blocked_state:
            condition = {
                "condition": "not",
                "conditions": [
                    {
                        "condition": "state",
                        "entity_id": entity_id,
                        "state": blocked_state,
                    }
                ],
            }
            if not _condition_exists(conditions, condition):
                conditions.append(condition)
                fixes.append(
                    f"Added missing top-level blocked-state guard for {entity_id}"
                )

    for guard in extract_negated_state_guards(prompt_text, entities):
        entity_id = str(guard.get("entity_id") or "").strip()
        state = str(guard.get("state") or "").strip()
        if not entity_id or not state:
            continue
        condition = {
            "condition": "not",
            "conditions": [
                {
                    "condition": "state",
                    "entity_id": entity_id,
                    "state": state,
                }
            ],
        }
        if not _condition_exists(conditions, condition):
            conditions.append(condition)
            fixes.append(
                f"Added missing top-level negated guard for {entity_id} != {state}"
            )


def _order_top_level_keys(parsed: dict[str, Any]) -> dict[str, Any]:
    """Return the automation mapping in a stable top-level key order."""
    ordered: dict[str, Any] = {}
    for key in ("alias", "description", "triggers", "conditions", "actions", "mode"):
        if key in parsed:
            ordered[key] = parsed[key]
    for key, value in parsed.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def autofix_yaml(
    yaml_text: str,
    prompt_text: str,
    entities: list[dict[str, Any]],
    resolved_entity_map: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, list[str]]:
    """Attempt to fix common YAML issues programmatically."""
    normalized_yaml = _normalize_automation_yaml_text(yaml_text)
    if not normalized_yaml:
        return yaml_text, []

    try:
        parsed = yaml.safe_load(normalized_yaml)
    except yaml.YAMLError:
        return yaml_text, []

    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        return yaml_text, []

    original = copy.deepcopy(parsed)
    fixes: list[str] = []
    entity_map = resolved_entity_map or build_entity_resolution_map(prompt_text, entities)

    if "trigger" in parsed and "triggers" not in parsed and isinstance(parsed["trigger"], list):
        parsed["triggers"] = parsed.pop("trigger")
        fixes.append("Renamed top-level trigger: to triggers:")
    if "action" in parsed and "actions" not in parsed and isinstance(parsed["action"], list):
        parsed["actions"] = parsed.pop("action")
        fixes.append("Renamed top-level action: to actions:")
    if "condition" in parsed and "conditions" not in parsed and isinstance(parsed["condition"], list):
        parsed["conditions"] = parsed.pop("condition")
        fixes.append("Renamed top-level condition: to conditions:")

    if "weekday" in parsed:
        weekdays = parsed.pop("weekday")
        if weekdays:
            parsed.setdefault("conditions", [])
            if isinstance(parsed["conditions"], list):
                parsed["conditions"].append(
                    {
                        "condition": "time",
                        "weekday": weekdays if isinstance(weekdays, list) else [weekdays],
                    }
                )
                fixes.append("Moved top-level weekday: into a time condition block")

    triggers = parsed.get("triggers")
    if isinstance(triggers, list):
        for trigger in triggers:
            if isinstance(trigger, dict):
                _fix_trigger_mapping(trigger, fixes)

    parsed.setdefault("conditions", [])
    if not isinstance(parsed["conditions"], list):
        parsed["conditions"] = []

    actions = parsed.get("actions")
    if isinstance(actions, list):
        parsed["actions"] = _fix_action_list(
            actions,
            prompt_text,
            entity_map,
            fixes,
            fallback_conditions=parsed["conditions"],
        )

    _ensure_guard_conditions(parsed, prompt_text, entities, fixes)

    if parsed == original:
        return normalized_yaml, []

    fixed_yaml = yaml.safe_dump(
        _order_top_level_keys(parsed),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).strip()
    return fixed_yaml, list(dict.fromkeys(fixes))
