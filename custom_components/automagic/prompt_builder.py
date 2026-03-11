"""Build the LLM prompt for automation generation."""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert Home Assistant automation engineer.
You will be given a plain-English description of a desired automation and a list of \
available entities in the user's Home Assistant installation.

Your job is to produce a valid Home Assistant automation in YAML format.

SYNTAX RULES - this is critical:
- Always use the HA 2024.10+ syntax. No exceptions.
- Use 'triggers:' (plural) for the trigger list
- Use 'trigger:' (singular) as the key inside each trigger item - NOT 'platform:'
- Use 'conditions:' (plural) for conditions
- Use 'actions:' (plural) for the action list
- Use 'action:' for service calls - NEVER use 'service:'

Example of correct syntax:
  triggers:
    - trigger: state
      entity_id: binary_sensor.front_door
      to: "on"
  actions:
    - action: light.turn_on
      target:
        entity_id: light.hallway

OUTPUT RULES:
- Only use entity_ids from the provided entity list. Never invent entity_ids.
- Output ONLY a JSON object with two keys:
    "yaml": the complete automation YAML as a string
    "summary": a 1-2 sentence plain English description of what the automation does
- Do not include any explanation, preamble, or markdown code fences outside the JSON.
- The YAML must include: alias, description, triggers, and actions at minimum.
- Use the most appropriate trigger type for the request. Prefer state triggers over \
template triggers where possible.
- If the request is ambiguous or references entities not in the list, make the best \
reasonable substitution and note it in the summary.
- If the request cannot be fulfilled with the available entities, set yaml to null and \
explain in the summary.\
"""


def build_prompt(user_input: str, entity_summary: str) -> list[dict[str, str]]:
    """Construct the OpenAI-compatible messages array for automation generation.

    Args:
        user_input: The user's natural-language automation description.
        entity_summary: The formatted entity list string from entity_collector.

    Returns:
        A list of message dicts with 'role' and 'content' keys.
    """
    user_message = (
        f"Available entities:\n{entity_summary}\n\n"
        f"Create an automation for:\n{user_input}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    _LOGGER.debug(
        "Built prompt: system=%d chars, user=%d chars",
        len(SYSTEM_PROMPT),
        len(user_message),
    )

    return messages
