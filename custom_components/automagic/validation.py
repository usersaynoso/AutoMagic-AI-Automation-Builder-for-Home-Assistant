"""Structured validation for generated automation YAML."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

import yaml

from .automation_writer import (
    AutomationValidationError,
    _TOP_LEVEL_WEEKDAY_ERROR,
    _bare_action_condition_error,
    _nested_trigger_mapping_error,
    validate_automation,
)
from .entity_collector import (
    build_entity_resolution_map,
    extract_explicit_state_guards,
    extract_negated_state_guards,
)
from .llm_client import _normalize_automation_yaml_text


_LIGHT_ATTRIBUTE_RE = re.compile(
    r"\b(color_temp|kelvin|color_name|rgb_color|xy_color|brightness_pct|brightness)\b",
    re.IGNORECASE,
)
_LIGHT_TURN_ON_BLOCK_RE = re.compile(
    r"action:\s*light\.turn_on[\s\S]{0,500}?(?=\n\s*-\s|\n[a-z_]+\s*:|\Z)",
    re.IGNORECASE,
)
_TOP_LEVEL_SECTION_RE = re.compile(r"^[a-z_][a-z0-9_]*\s*:", re.IGNORECASE)
_TIMEOUT_BRANCH_PROMPT_RE = re.compile(
    r"\b(if.{0,80}(not finished|still running|still active|hasn.t finished|stuck)"
    r"|still.{0,40}after.{0,20}\d+\s*(hour|minute|min))\b",
    re.IGNORECASE,
)
_CONDITIONAL_NOTIFY_PROMPT_RE = re.compile(
    r"\b(if.{0,60}(not finished|still|stuck|hasn.t|hasn't)|"
    r"(notify|notification|message).{0,60}(if|only if|when))\b",
    re.IGNORECASE,
)
_PROMPT_WEEKDAY_RE = re.compile(r"\bweekday(?:s)?\b", re.IGNORECASE)
_PROMPT_COLOUR_RE = re.compile(
    r"\b(warm white|warm light|colour|color|red|blue|green|amber|\d{4}\s*k)\b",
    re.IGNORECASE,
)
_PROMPT_OFF_PATH_RE = re.compile(
    r"\b(turn .* back off|off when|when .* finishes|when .* finish)\b",
    re.IGNORECASE,
)


@dataclass
class ValidationReport:
    """Structured automation validation report."""

    syntax_errors: list[str] = field(default_factory=list)
    missing_entities: list[str] = field(default_factory=list)
    missing_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    structural_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_autofixable_issues(self) -> bool:
        """Return True when deterministic fixes are available."""
        return bool(self.syntax_errors or self.missing_entities or self.missing_data)

    @property
    def has_blocking_issues(self) -> bool:
        """Return True when installability is still blocked."""
        return bool(self.syntax_errors or self.structural_issues)

    @property
    def needs_llm_repair(self) -> bool:
        """Return True when structural issues remain after autofix."""
        return bool(self.structural_issues)

    def issue_strings(self) -> list[str]:
        """Flatten the report into human-readable issue strings."""
        issues = [
            *self.syntax_errors,
            *self.missing_entities,
            *self.structural_issues,
        ]
        for key, payload in self.missing_data.items():
            message = str(payload.get("message") or "").strip()
            issues.append(message or key)
        return list(dict.fromkeys(issue for issue in issues if issue))

    def as_constraint_text(self) -> str:
        """Format remaining issues as a compact constraint block."""
        issues = self.issue_strings()
        if not issues:
            return ""
        return "CONSTRAINTS:\n- " + "\n- ".join(issues[:12])


def _append_unique(target: list[str], message: str) -> None:
    """Append a unique non-empty message."""
    text = str(message or "").strip()
    if text and text not in target:
        target.append(text)


def _validate_generated_yaml_syntax(yaml_text: str) -> str | None:
    """Return a validation error string when the YAML is invalid."""
    normalized_yaml = _normalize_automation_yaml_text(yaml_text)
    if not normalized_yaml:
        return "The response did not include automation YAML."

    try:
        parsed = yaml.safe_load(normalized_yaml)
    except yaml.YAMLError as err:
        return f"Invalid YAML: {err}"

    try:
        validate_automation(parsed)
    except AutomationValidationError as err:
        return str(err)

    return None


def _walk_for_entity_ids(obj: Any, entity_ids: set[str]) -> None:
    """Walk YAML data collecting entity references and notify services."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "entity_id":
                if isinstance(value, str) and "." in value:
                    entity_ids.add(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and "." in item:
                            entity_ids.add(item)
            elif key == "action" and isinstance(value, str) and value.startswith("notify."):
                entity_ids.add(value)
            else:
                _walk_for_entity_ids(value, entity_ids)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_entity_ids(item, entity_ids)


def extract_entity_ids_from_yaml(yaml_text: str) -> set[str]:
    """Extract entity references from a YAML string."""
    normalized_yaml = _normalize_automation_yaml_text(yaml_text)
    if not normalized_yaml:
        return set()
    try:
        parsed = yaml.safe_load(normalized_yaml)
    except yaml.YAMLError:
        return set()
    if not isinstance(parsed, dict):
        return set()
    entity_ids: set[str] = set()
    _walk_for_entity_ids(parsed, entity_ids)
    return entity_ids


def _extract_weekdays(prompt_text: str) -> list[str]:
    """Extract weekday abbreviations from prompt text."""
    text = str(prompt_text or "").strip().lower()
    if not text:
        return []
    if re.search(r"\bevery weekday(?:s)?\b|\beach weekday\b", text):
        return ["mon", "tue", "wed", "thu", "fri"]
    if re.search(r"\bevery weekend(?:s)?\b|\beach weekend\b", text):
        return ["sat", "sun"]
    mappings = (
        ("monday", "mon"),
        ("tuesday", "tue"),
        ("wednesday", "wed"),
        ("thursday", "thu"),
        ("friday", "fri"),
        ("saturday", "sat"),
        ("sunday", "sun"),
    )
    return [short for word, short in mappings if re.search(rf"\b{word}s?\b", text)]


def _yaml_has_weekdays(yaml_text: str, weekdays: list[str]) -> bool:
    """Return True when all requested weekdays are present."""
    normalized = str(yaml_text or "").lower()
    if "weekday:" not in normalized:
        return False
    return all(re.search(rf"^\s*-\s*{weekday}\s*$", normalized, re.MULTILINE) for weekday in weekdays)


def _yaml_guard_is_in_conditions_block(yaml_text: str, entity_id: str) -> bool:
    """Return True when the entity appears in the top-level conditions block."""
    if not yaml_text or not entity_id:
        return False
    in_conditions = False
    for line in yaml_text.splitlines():
        if re.match(r"^conditions\s*:", line):
            in_conditions = True
            continue
        if in_conditions:
            if _TOP_LEVEL_SECTION_RE.match(line) and not line.startswith(" "):
                break
            if entity_id in line:
                return True
    return False


def _yaml_has_positive_state_guard(yaml_text: str, entity_id: str, state: str) -> bool:
    """Return True when YAML contains entity == state as a condition."""
    return bool(
        re.search(
            rf"entity_id:\s*{re.escape(entity_id)}[\s\S]{{0,180}}state:\s*['\"]?{re.escape(state)}['\"]?",
            yaml_text,
            re.IGNORECASE,
        )
    )


def _yaml_has_negated_state_guard(yaml_text: str, entity_id: str, state: str) -> bool:
    """Return True when YAML contains entity != state as a condition."""
    patterns = (
        rf"condition:\s*not[\s\S]{{0,260}}entity_id:\s*{re.escape(entity_id)}[\s\S]{{0,180}}state:\s*['\"]?{re.escape(state)}['\"]?",
        rf"value_template:\s*>?-?[\s\S]{{0,320}}states?\(['\"]{re.escape(entity_id)}['\"]\)\s*!=\s*['\"]{re.escape(state)}['\"]",
        rf"value_template:\s*>?-?[\s\S]{{0,320}}not\s+is_state\(['\"]{re.escape(entity_id)}['\"],\s*['\"]{re.escape(state)}['\"]\)",
    )
    return any(re.search(pattern, yaml_text, re.IGNORECASE) for pattern in patterns)


def _collect_static_issues(normalized_yaml: str, parsed: Any, report: ValidationReport) -> None:
    """Collect prompt-independent validation issues."""
    if isinstance(parsed, dict):
        if "weekday" in parsed:
            _append_unique(report.syntax_errors, _TOP_LEVEL_WEEKDAY_ERROR)

        triggers = parsed.get("triggers")
        if isinstance(triggers, list):
            for index, trigger_item in enumerate(triggers):
                if isinstance(trigger_item, dict) and isinstance(trigger_item.get("trigger"), dict):
                    _append_unique(report.syntax_errors, _nested_trigger_mapping_error(index))

        actions = parsed.get("actions")
        if isinstance(actions, list):
            for index, action_item in enumerate(actions):
                if isinstance(action_item, dict) and "condition" in action_item:
                    _append_unique(report.syntax_errors, _bare_action_condition_error(index))

    for match in re.finditer(r"\bcolor_temp\s*:\s*(\d+)\b", normalized_yaml, re.IGNORECASE):
        value = int(match.group(1))
        if value <= 1000:
            continue
        report.missing_data.setdefault(
            f"color_temp:{value}",
            {
                "message": (
                    f"color_temp value {value} looks like Kelvin. Convert it to mireds "
                    "with round(1000000 / kelvin)."
                )
            },
        )

    if re.search(
        r"\bcolor_name:\s*['\"]?[a-z0-9]+_[a-z0-9_]+['\"]?",
        normalized_yaml,
        re.IGNORECASE,
    ):
        report.missing_data.setdefault(
            "color_name",
            {
                "message": (
                    "Use a valid Home Assistant light color. Replace underscore-separated "
                    "values like warm_white with mired-based color_temp or a valid color name."
                )
            },
        )


def validate_generated_yaml(
    prompt_text: str,
    entities: list[dict[str, Any]],
    yaml_text: str,
    entity_map: dict[str, dict[str, Any]] | None = None,
) -> ValidationReport:
    """Return a structured validation report for generated YAML."""
    report = ValidationReport()
    syntax_issue = _validate_generated_yaml_syntax(yaml_text)
    if syntax_issue:
        _append_unique(report.syntax_errors, syntax_issue)

    normalized_yaml = _normalize_automation_yaml_text(yaml_text)
    parsed_yaml: Any = None
    if normalized_yaml:
        try:
            parsed_yaml = yaml.safe_load(normalized_yaml)
        except yaml.YAMLError:
            parsed_yaml = None

    _collect_static_issues(normalized_yaml, parsed_yaml, report)

    if not normalized_yaml or not prompt_text or not entities:
        return report

    entity_map = entity_map or build_entity_resolution_map(prompt_text, entities)
    yaml_entity_ids = extract_entity_ids_from_yaml(normalized_yaml)
    known_entity_ids = {
        str(entity.get("entity_id") or "").strip()
        for entity in entities
        if str(entity.get("entity_id") or "").strip()
    }
    hallucinated = sorted(entity_id for entity_id in yaml_entity_ids if entity_id not in known_entity_ids)
    if hallucinated:
        _append_unique(
            report.missing_entities,
            "Use only entity_ids from the provided entity map or entity list. Unknown entity_ids: "
            + ", ".join(hallucinated[:10])
            + ".",
        )

    weekdays = _extract_weekdays(prompt_text)
    if weekdays and not _yaml_has_weekdays(normalized_yaml, weekdays):
        _append_unique(
            report.structural_issues,
            "Preserve the requested weekday schedule in a valid time trigger or time condition.",
        )

    explicit_guards = extract_explicit_state_guards(prompt_text, entities)
    for guard in explicit_guards:
        entity_id = str(guard.get("entity_id") or "").strip()
        blocked_state = str(guard.get("blocked_state") or "").strip()
        required_state = str(guard.get("required_state") or "").strip()
        if not entity_id:
            continue
        if entity_id not in yaml_entity_ids:
            _append_unique(
                report.missing_entities,
                (
                    "The guard entity "
                    f"{entity_id} is missing entirely. Add it as a blocking top-level condition."
                ),
            )
            continue
        has_guard = False
        if required_state and _yaml_has_positive_state_guard(normalized_yaml, entity_id, required_state):
            has_guard = True
        elif blocked_state and _yaml_has_negated_state_guard(normalized_yaml, entity_id, blocked_state):
            has_guard = True
        if not has_guard:
            _append_unique(
                report.structural_issues,
                f"Respect the explicit guard {entity_id} before running the actions.",
            )
        elif not _yaml_guard_is_in_conditions_block(normalized_yaml, entity_id):
            _append_unique(
                report.structural_issues,
                (
                    f"Guard {entity_id} must be in the top-level conditions: block, "
                    "not nested inside actions or a choose branch."
                ),
            )

    for guard in extract_negated_state_guards(prompt_text, entities):
        entity_id = str(guard.get("entity_id") or "").strip()
        state = str(guard.get("state") or "").strip()
        if entity_id and state and not _yaml_has_negated_state_guard(normalized_yaml, entity_id, state):
            _append_unique(
                report.structural_issues,
                f"Preserve the blocked-state guard requiring {entity_id} to not be {state!r}.",
            )

    for label, payload in entity_map.items():
        entity_ids = [
            str(entity_id).strip()
            for entity_id in payload.get("entity_ids", []) or []
            if str(entity_id).strip()
        ]
        role = str(payload.get("role") or "").strip().lower()
        if not entity_ids:
            continue
        if role == "notify_target" and not any(entity_id in yaml_entity_ids for entity_id in entity_ids):
            _append_unique(
                report.missing_entities,
                (
                    f"Use the resolved notification target for {label}: "
                    + ", ".join(entity_ids)
                    + "."
                ),
            )
        if role == "action_target" and _PROMPT_COLOUR_RE.search(prompt_text):
            if not any(entity_id in yaml_entity_ids for entity_id in entity_ids):
                _append_unique(
                    report.missing_entities,
                    f"Include the resolved action target(s) for {label}: {', '.join(entity_ids)}.",
                )

    if _PROMPT_COLOUR_RE.search(prompt_text):
        light_blocks = _LIGHT_TURN_ON_BLOCK_RE.findall(normalized_yaml)
        if light_blocks and not all(_LIGHT_ATTRIBUTE_RE.search(block) for block in light_blocks):
            report.missing_data.setdefault(
                "light_colour_data",
                {
                    "message": (
                        "The prompt requests specific light colour or brightness data. "
                        "Every affected light.turn_on action must include color_temp, kelvin, "
                        "color_name, rgb_color, xy_color, or brightness_pct data."
                    )
                },
            )

    if (
        _CONDITIONAL_NOTIFY_PROMPT_RE.search(prompt_text)
        and re.search(r"delay:[\s\S]{0,400}?action:\s*notify\.", normalized_yaml, re.IGNORECASE)
        and not re.search(r"delay:[\s\S]{0,400}?choose:", normalized_yaml, re.IGNORECASE)
    ):
        _append_unique(
            report.structural_issues,
            "After a delay, re-check the relevant state before notifying instead of sending an unconditional notification.",
        )

    if (
        _TIMEOUT_BRANCH_PROMPT_RE.search(prompt_text)
        and re.search(r"wait_for_trigger", normalized_yaml, re.IGNORECASE)
        and not re.search(r"timeout\s*:", normalized_yaml, re.IGNORECASE)
    ):
        _append_unique(
            report.structural_issues,
            (
                "The automation uses wait_for_trigger without a timeout. Add timeout plus "
                "continue_on_timeout: true and branch on wait.completed."
            ),
        )

    if (
        _PROMPT_OFF_PATH_RE.search(prompt_text)
        and re.search(r"action:\s*light\.turn_on", normalized_yaml, re.IGNORECASE)
        and not re.search(r"action:\s*light\.turn_off", normalized_yaml, re.IGNORECASE)
    ):
        _append_unique(
            report.structural_issues,
            "The automation turns lights on but does not include an explicit off path.",
        )

    if _PROMPT_WEEKDAY_RE.search(prompt_text) and not weekdays:
        _append_unique(
            report.warnings,
            "The prompt mentions weekdays, but the validator could not infer the exact day set.",
        )

    return report
