"""Tests for structured YAML validation reports."""

from __future__ import annotations

from custom_components.automagic.validation import (
    ValidationReport,
    validate_generated_yaml,
)


def test_validation_report_flags_guard_placement_and_missing_light_data():
    """Prompt-aware validation should separate structural and data issues."""
    prompt = (
        "When the front door opens, turn the bar lamp warm white at 20% brightness. "
        "Don't start it if the router LED switch is already off."
    )
    entities = [
        {
            "entity_id": "binary_sensor.front_door",
            "name": "Front Door",
            "domain": "binary_sensor",
        },
        {
            "entity_id": "light.bar_lamp",
            "name": "Bar Lamp",
            "domain": "light",
        },
        {
            "entity_id": "switch.router_led",
            "name": "Router LED Switch",
            "domain": "switch",
        },
    ]
    yaml_text = """alias: Warm Lamp
description: Example
triggers:
  - trigger: state
    entity_id: binary_sensor.front_door
    to: "on"
conditions: []
actions:
  - choose:
      - conditions:
          - condition: state
            entity_id: switch.router_led
            state: "on"
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.bar_lamp
mode: single
"""

    report = validate_generated_yaml(prompt, entities, yaml_text)

    assert report.has_blocking_issues is True
    assert any("top-level conditions" in issue for issue in report.structural_issues)
    assert "light_colour_data" in report.missing_data
    assert "CONSTRAINTS:" in report.as_constraint_text()


def test_validation_report_tracks_unknown_entities_as_autofixable():
    """Hallucinated entity ids should be surfaced separately from syntax errors."""
    report = validate_generated_yaml(
        "Turn on the bar lamp.",
        [
            {
                "entity_id": "light.bar_lamp",
                "name": "Bar Lamp",
                "domain": "light",
            }
        ],
        """alias: Bad Entity
description: Example
triggers:
  - trigger: time
    at: "08:00:00"
conditions: []
actions:
  - action: light.turn_on
    target:
      entity_id: light.made_up
mode: single
""",
    )

    assert report.has_autofixable_issues is True
    assert any("Unknown entity_ids" in issue for issue in report.missing_entities)


def test_validation_report_constraint_text_is_compact_and_ordered():
    """Constraint rendering should preserve issue order for regeneration prompts."""
    report = ValidationReport(
        syntax_errors=["Use triggers:, not trigger:."],
        structural_issues=["Move the guard to top-level conditions."],
    )

    assert report.as_constraint_text() == (
        "CONSTRAINTS:\n"
        "- Use triggers:, not trigger:.\n"
        "- Move the guard to top-level conditions."
    )
