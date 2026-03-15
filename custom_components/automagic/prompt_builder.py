"""Build the LLM prompt for automation generation."""

from __future__ import annotations

import logging
import re

from .entity_collector import (
    _collect_semantic_prompt_matches,
    _expand_variant_entities,
    _find_obvious_named_entities,
    _tokenize,
    _normalize_phrase,
    _relevant_domain_matches,
    build_entity_resolution_map,
)
from .intent_schema import INTENT_JSON_SCHEMA

_LOGGER = logging.getLogger(__name__)
_GROUP_MARKER_RE = re.compile(
    r"\b(all|both|three|every|each|single phase|phase|phases|zones|channels|outputs|inputs)\b"
)
_VARIANT_SUFFIX_RE = re.compile(
    r"_(?:l\d+|phase_?\d+|\d+|left|right|rear|front|north|south|east|west|upstairs|downstairs)$"
)
_GROUP_CLAUSE_IGNORE_TOKENS = {
    "ac",
    "automation",
    "entity",
    "entities",
    "input",
    "output",
    "phase",
    "phases",
    "sensor",
}

SYSTEM_PROMPT = """\
You are an expert Home Assistant automation engineer.
You will be given a plain-English description of a desired automation and a list of \
available entities in the user's Home Assistant installation.
The conversation may continue with follow-up questions, clarifications, corrections, \
or requested changes to the current automation.

Your job is to produce a valid Home Assistant automation in YAML format.

SYNTAX RULES - this is critical:
- Always use the HA 2024.10+ syntax. No exceptions.
- Use 'triggers:' (plural) for the trigger list
- Use 'trigger:' (singular) as the key inside each trigger item - NOT 'platform:'
- Use 'conditions:' (plural) for conditions
- Use 'actions:' (plural) for the action list
- Use 'action:' for service calls - NEVER use 'service:'
- action values must be exactly <domain>.<service_name> (e.g. light.turn_on, \
notify.mobile_app_iphone). NEVER put an entity_id in the action value. \
Use a separate target: entity_id: field for the entity.

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
- If the provided list includes notify.* entries, you may use those exact notify action \
service names in actions. Do not invent notify services.
- Output ONLY a JSON object with four keys:
    "yaml": the complete automation YAML as a string, or null when clarification is required
    "summary": a 1-2 sentence plain English description of what the automation does, or a brief explanation of what is missing
    "needs_clarification": true or false
    "clarifying_questions": an array of 0-3 short, specific questions
- Do not include any explanation, preamble, or markdown code fences outside the JSON.
- The yaml string itself must start directly with alias:. Do not prefix it with yaml, \
yaml:, automation:, sequence:, a list item, or markdown fences.
- Keep the YAML concise. Do not add comments or explanatory prose inside or after the YAML.
- The YAML must include: alias, description, triggers, and actions at minimum.
- For notify.* actions, put the notification text under data: with a message key.
- Use the most appropriate trigger type for the request. Prefer state triggers over \
template triggers where possible.
- If an entity_id is listed in the provided entity list, treat it as available for YAML \
generation even if its current state is "unknown" or "unavailable". Only ask for \
clarification when the needed entity is missing entirely.
- When prompt-specific guidance includes resolved entity, grouped-family, automation-guard, \
or notification-target mappings, treat those mappings as authoritative and use them \
without asking the user to choose again.
- For follow-up change requests, revise the current automation and return the full \
updated YAML, not a partial diff.
- For follow-up questions about the current automation, answer briefly in "summary" and \
also return the full current or updated YAML in "yaml".
- For complex multi-step requests, use variables, choose blocks, delay/wait steps, and \
template conditions or template values as needed. Return one complete automation unless \
the user explicitly asks for multiple automations.
- When the prompt requires waiting for an event (such as a device finishing) but \
also specifies a maximum wait time after which a different action should happen, \
use wait_for_trigger with a timeout: (in HH:MM:SS format) and \
continue_on_timeout: true. After the wait, use a choose: block that branches on \
{{ wait.completed }} to distinguish between the event occurring (true) and the \
timeout expiring (false). Do not use an unconditional delay for this pattern as \
it ignores whether the event happened.
- When the prompt requests a specific colour or brightness for lights, every affected \
light.turn_on action MUST include a data: block with at least one colour field \
(color_temp in mireds, color_name, rgb_color, or kelvin) and brightness_pct. \
Never drop colour or brightness attributes to resolve a different error.
- Read the entire request as one combined condition/action sequence before deciding \
anything is missing. Do not ask about a sub-step when the needed threshold, guard, time \
window, or follow-up action is already stated elsewhere in the same prompt.
- Interpret wattage/watts/kW as power, amps/amperage as current, and volts as voltage \
when matching sensor families from the provided entities.
- Treat time-window guards or exclusions such as "not between 9am and 5pm on a \
weekday" as conditions, not as the automation's trigger schedule.
- When the user says "don't start/run X if Y is already off/on", encode that as a \
blocking condition in the top-level conditions: block, not as a choose: branch inside \
actions:. The automation should not execute at all when the guard fails.
- Preserve the user's boolean logic exactly when they combine OR and AND clauses across \
different sensor or entity families.
- When the user asks to report whichever sensor triggered, capture the triggering sensor \
name and value in variables so the notification text includes the real sensor and reading.
- When a matched entity has sibling variants such as left/right, L1/L2/L3, or numbered \
variants, and the user asks for all/both/three/every member of the set, include the full \
relevant sibling set.
- When the user refers to any/all/both/three/every member of a sibling set, use the whole \
listed set together and do not ask which single entity to use if the set is already present.
- When different threshold or state clauses clearly refer to different entity families, map \
each clause to its matching family and use all listed siblings in that family together. Do \
not ask the user to choose just one family when the prompt already distinguishes the families.
- When the prompt says to turn lights on while a device or process is active and off when \
it finishes, the automation MUST include an explicit off sequence. Use a state trigger on \
the device reaching its finished/idle/docked state, or a wait_for_trigger inside the \
actions block, followed by light.turn_off. Do not leave lights on indefinitely with no off path.
- If a follow-up question would only restate a threshold, delay branch, or fallback action \
that is already explicit in the user's prompt, use the exact prompt clause instead of asking \
again.
- When the user refers to a named automation concept such as a balance, bedtime, heating, \
washing, or security automation, match the provided automation.* entities whose names share \
that concept. Use the matching automation entities as guards or conditions without asking \
which single automation to use when the concept is already specific enough.
- When the user names a phone, tablet, or mobile device and a matching notify.* service is \
present in the provided list, use that notify service directly instead of asking again which \
notification target to use.
- Preserve exact thresholds, colors, brightness, flash counts, delays, weekday/time \
exclusions, and guard conditions from the user's request unless they conflict.
- If you are unsure which available entity matches the user's intent, ask a clarifying \
question instead of guessing.
- If the user explicitly names an entity_id that exists in the provided list, treat it as \
authoritative and do not ask again which entity to use.
- If a provided entity name is an exact or near-exact match for the user's wording, use \
that entity directly without asking for confirmation.
- Home Assistant's built-in sun trigger is allowed for sunrise/sunset automations even \
when no sun entity_id is listed.
- Clear schedule phrases like "at 10am every morning", "every day at 7:30", "every \
weekday", or "at sunset" are already specific enough for a trigger and should not cause \
clarification.
- If there is one obvious entity match, you may substitute it and note that in the summary.
- If a missing detail would materially change the automation, do not guess. Set \
yaml to null, needs_clarification to true, and ask the minimum number of direct questions needed.
- Material missing details include things like target entity, area, time, day, threshold, \
duration, scene, notification target, brightness, color, or action mode.
- Do not mark the task complete with an empty yaml string.
- If the request cannot be fulfilled with the available entities even after clarification, \
set yaml to null, needs_clarification to false, and explain why in the summary.\
"""

INTENT_SYSTEM_PROMPT = f"""\
You are an expert Home Assistant automation engineer.
You will be given a plain-English description of a desired automation and a list of available entities in the user's Home Assistant installation.
The conversation may continue with follow-up questions, clarifications, corrections, or requested changes to the current automation.

Your job is to return structured automation intent, not raw YAML.

OUTPUT RULES:
- Return only a JSON object with exactly two primary keys:
    "intent": the structured automation intent object
    "summary": a 1-2 sentence plain English description of what the automation does
- You may also include:
    "needs_clarification": true
    "clarifying_questions": an array of 0-3 short, specific questions
- Do NOT return YAML. Return only the structured intent JSON. The YAML will be assembled automatically from your intent.
- Do not include markdown fences, commentary, or any text outside the JSON object.
- Every entity_id in your response must come from the ENTITY MAP or the full entity list supplied by the user. Do not invent entity_ids.

INTENT SCHEMA:
{INTENT_JSON_SCHEMA}

EXAMPLES:
Example 1 user request:
"Turn on <light_entity> at 07:00 every weekday."
Example 1 response:
{{
  "intent": {{
    "alias": "Weekday morning lights",
    "description": "Turns on the requested light at 07:00 on weekdays.",
    "mode": "single",
    "triggers": [{{"type": "time", "at": "07:00:00"}}],
    "conditions": [{{"type": "time", "weekday": ["mon", "tue", "wed", "thu", "fri"]}}],
    "action_sequence": [
      {{
        "step_type": "service_call",
        "action": "light.turn_on",
        "target_entity_ids": ["<light_entity>"]
      }}
    ]
  }},
  "summary": "Turns on the requested light every weekday at 07:00."
}}

Example 2 user request:
"When <trigger_entity> turns on, set <light_one> and <light_two> to warm white at 20% brightness."
Example 2 response:
{{
  "intent": {{
    "alias": "Warm light response",
    "description": "Turns two lights on to a dim warm white when the trigger entity turns on.",
    "mode": "restart",
    "triggers": [{{"type": "state", "entity_id": "<trigger_entity>", "to": "on"}}],
    "conditions": [],
    "action_sequence": [
      {{
        "step_type": "service_call",
        "action": "light.turn_on",
        "target_entity_ids": ["<light_one>", "<light_two>"],
        "data": {{"color_temp": 370, "brightness_pct": 20}}
      }}
    ]
  }},
  "summary": "Turns the requested lights on to dim warm white when the trigger entity turns on."
}}

Example 3 user request:
"If <machine_sensor> is still active after 2 hours, notify <notify_service>."
Example 3 response:
{{
  "intent": {{
    "alias": "Machine timeout notify",
    "description": "Waits for the machine to finish and notifies if it remains active after two hours.",
    "mode": "single",
    "triggers": [{{"type": "state", "entity_id": "<machine_sensor>", "to": "active"}}],
    "conditions": [],
    "action_sequence": [
      {{
        "step_type": "wait_for_trigger",
        "wait_triggers": [{{"type": "state", "entity_id": "<machine_sensor>", "to": "idle"}}],
        "timeout": "02:00:00"
      }},
      {{
        "step_type": "choose",
        "choose_options": [
          {{
            "conditions": [{{"type": "template", "value_template": "{{{{ not wait.completed }}}}"}}],
            "sequence": [
              {{
                "step_type": "service_call",
                "action": "<notify_service>",
                "data": {{"message": "The device is still active after 2 hours."}}
              }}
            ]
          }}
        ],
        "choose_default": []
      }}
    ]
  }},
  "summary": "Notifies if the device is still active after a two-hour wait."
}}

GENERATION RULES:
- Always use Home Assistant 2024.10+ semantics in the intent so the assembler can emit triggers:, conditions:, actions:, and action: correctly.
- Read the entire request as one combined condition/action sequence before deciding anything is missing.
- Treat time-window exclusions such as "not between 9am and 5pm on a weekday" as conditions, not as the trigger schedule.
- When the user says "don't start/run X if Y is already off/on", encode that as a blocking top-level condition, not as a choose branch inside actions.
- Preserve thresholds, colours, brightness levels, delays, timeouts, weekdays, guard conditions, sibling-group expansion, and notification messages from the user's request.
- When the prompt requires waiting for an event and also specifies a maximum wait time, use wait_for_trigger with timeout and structure the follow-up around wait.completed.
- When the request targets all/both/every member of a sibling entity family, include the complete resolved set together.
- When the user names a phone or mobile device and a matching notify.* service exists, use that notify service directly.
- When the prompt requests lights on while a device is active and back off when it finishes, include an explicit off path in the action_sequence.
- If the request cannot be implemented without guessing after using the entity map and entity list, set needs_clarification to true and ask the minimum number of direct questions needed.
"""

INTENT_REPAIR_SYSTEM_PROMPT = f"""\
You are an expert Home Assistant automation intent repair assistant.
Return only a JSON object with the keys intent, summary, needs_clarification, and clarifying_questions.
Do not return YAML.
Use this schema exactly:
{INTENT_JSON_SCHEMA}

Repair rules:
- Keep the user's original automation behavior, guards, thresholds, delays, and notifications.
- Replace invalid or invented entity_ids with exact entity_ids from the supplied ENTITY MAP or entity list.
- Do not drop colour, brightness, timeout, weekday, or choose-branch logic when fixing another issue.
- Ask for clarification only if the original request still cannot be implemented without guessing.
"""


def _build_prompt_guidance(
    user_input: str, entities: list[dict[str, str]] | None
) -> list[str]:
    """Return compact, prompt-specific mapping hints for the LLM."""
    if not entities:
        return []

    guidance: list[str] = []
    obvious_entities = _find_obvious_named_entities(user_input, entities, 8)
    semantic_matches = _collect_semantic_prompt_matches(user_input, entities, 4)
    grouped_entities = _expand_variant_entities(
        user_input,
        entities,
        [
            *obvious_entities,
            *[
                entity
                for match in semantic_matches
                for entity in match.get("entities", [])
            ],
        ],
    )
    automation_matches = (
        _relevant_domain_matches(user_input, entities, "automation", 2, 4)
        if "automation" in _normalize_phrase(user_input)
        else []
    )
    notify_matches = (
        _relevant_domain_matches(user_input, entities, "notify", 1, 3)
        if re.search(
            r"\b(notify|notification|iphone|phone|mobile)\b",
            _normalize_phrase(user_input),
        )
        else []
    )
    group_clause_mappings = _build_group_clause_mappings(user_input, entities)

    if obvious_entities:
        guidance.append(
            "High-confidence entity name matches: "
            + "; ".join(
                f"{entity['name']} -> {entity['entity_id']}"
                for entity in obvious_entities[:6]
            )
            + "."
        )

    if semantic_matches:
        guidance.append(
            "Semantic entity-family matches inferred from the request wording: "
            + "; ".join(
                f"{match['label']} -> "
                + ", ".join(
                    entity["entity_id"] for entity in match.get("entities", [])[:4]
                )
                for match in semantic_matches[:4]
            )
            + "."
        )

    if grouped_entities:
        guidance.append(
            "Grouped sibling entities that should stay together: "
            + ", ".join(entity["entity_id"] for entity in grouped_entities[:12])
            + "."
        )

    if group_clause_mappings:
        guidance.append(
            "Resolved grouped clause mappings from the request: "
            + "; ".join(
                f"{mapping['label']} -> "
                + ", ".join(mapping["entities"])
                + f' for "{mapping["clause"]}"'
                for mapping in group_clause_mappings[:4]
            )
            + "."
        )

    if automation_matches:
        guidance.append(
            "Resolved automation guard matches from the request: "
            + ", ".join(
                entity["entity_id"] for entity in automation_matches[:4]
            )
            + "."
        )

    if notify_matches:
        guidance.append(
            "Resolved notification target matches from the request: "
            + "; ".join(
                f"{entity['name']} -> {entity['entity_id']}"
                for entity in notify_matches[:3]
            )
            + "."
        )

    return guidance


def _variant_stem(entity_id: str) -> str:
    """Return a canonical entity stem for sibling expansion."""
    normalized = str(entity_id or "").lower()
    return _VARIANT_SUFFIX_RE.sub("", normalized)


def _collect_sibling_groups(
    user_input: str, entities: list[dict[str, str]] | None
) -> list[list[dict[str, str]]]:
    """Collect grouped sibling entity families implied by the prompt."""
    if not entities or not _GROUP_MARKER_RE.search(str(user_input or "")):
        return []

    grouped: dict[str, list[dict[str, str]]] = {}
    for entity in entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id:
            continue
        grouped.setdefault(_variant_stem(entity_id), []).append(entity)

    return [group for group in grouped.values() if len(group) >= 2]


def _sibling_group_label(group: list[dict[str, str]]) -> str:
    """Return a readable label for a sibling entity family."""
    if not group:
        return ""
    first_name = str(group[0].get("name") or "").strip()
    return re.sub(
        r"\s+(L\d+|\d+|Left|Right|Rear|Front|North|South|East|West|Upstairs|Downstairs)$",
        "",
        first_name,
        flags=re.IGNORECASE,
    ).strip()


def _extract_prompt_clauses(user_input: str) -> list[str]:
    """Split a user prompt into coarse clauses for auto-clarification answers."""
    return [
        clause.strip()
        for clause in re.split(r"(?<=[.!?])\s+|\s+\bthen\b\s+|\s+\bor\b\s+|,\s*", str(user_input or ""))
        if clause.strip()
    ]


def _build_group_clause_mappings(
    user_input: str, entities: list[dict[str, str]] | None
) -> list[dict[str, object]]:
    """Map grouped sibling families back to the threshold clauses that mention them."""
    sibling_groups = _collect_sibling_groups(user_input, entities)
    normalized_prompt = _normalize_phrase(user_input)
    if not normalized_prompt or not sibling_groups:
        return []

    clauses = [
        clause.strip()
        for clause in re.split(
            r"\s+\bor\b\s+|\s+\bthen\b\s+|[.;]\s*",
            normalized_prompt,
            flags=re.IGNORECASE,
        )
        if clause.strip()
    ]

    mappings: list[dict[str, object]] = []
    for group in sibling_groups:
        label = _sibling_group_label(group)
        label_tokens = [
            token
            for token in _tokenize(label)
            if token not in _GROUP_CLAUSE_IGNORE_TOKENS
        ]
        if not label_tokens:
            continue

        best_clause = ""
        best_score = 0
        for clause in clauses:
            score = sum(1 for token in label_tokens if token in clause)
            if re.search(
                r"\b(above|below|greater|less|exceeds|drops|between|outside|inside|equals|not)\b",
                clause,
                flags=re.IGNORECASE,
            ):
                score += 1
            if score > best_score:
                best_score = score
                best_clause = clause

        if best_score <= 0 or not best_clause:
            continue

        mappings.append(
            {
                "label": label,
                "clause": best_clause,
                "entities": [entity["entity_id"] for entity in group],
            }
        )

    return mappings


def _build_prompt_clause_auto_answer(
    user_input: str, clarifying_questions: list[str]
) -> str:
    """Quote already-specified prompt clauses back to the model when relevant."""
    clauses = _extract_prompt_clauses(user_input)
    if not clauses or not clarifying_questions:
        return ""

    selected_clauses: list[str] = []
    for question in clarifying_questions:
        question_tokens = [
            token
            for token in _tokenize(question)
            if token not in _GROUP_CLAUSE_IGNORE_TOKENS
        ]
        if not question_tokens:
            continue

        best_clause = ""
        best_score = 0
        for clause in clauses:
            normalized_clause = _normalize_phrase(clause)
            score = sum(
                1 for token in question_tokens if token in normalized_clause
            )
            if re.search(
                r"\b(per phase|single phase|during the .* wait|wait|threshold|drops below|exceeds|above)\b",
                question,
                flags=re.IGNORECASE,
            ) and re.search(
                r"\b(single phase|wait|drops below|exceeds|above)\b",
                clause,
                flags=re.IGNORECASE,
            ):
                score += 2
            if score > best_score:
                best_score = score
                best_clause = clause

        if best_score >= 2 and best_clause:
            selected_clauses.append(best_clause)

    unique_clauses = list(dict.fromkeys(selected_clauses))
    if not unique_clauses:
        return ""

    quoted_clauses = " ".join(f'"{clause}"' for clause in unique_clauses)
    return (
        "The original prompt already specifies these details. Use these exact clauses: "
        f"{quoted_clauses}. Continue and return the automation JSON."
    )


def build_auto_clarification_answer(
    user_input: str,
    result: dict[str, object],
    entities: list[dict[str, str]] | None,
) -> str:
    """Return a generic auto-answer for grouped clarification loops when possible."""
    clarifying_questions = [
        str(question).strip()
        for question in result.get("clarifying_questions", []) or []
        if str(question).strip()
    ]
    clarification_text = _normalize_phrase(
        f"{result.get('summary', '')} {' '.join(clarifying_questions)}"
    )
    prompt_clause_answer = _build_prompt_clause_auto_answer(
        user_input, clarifying_questions
    )
    if prompt_clause_answer and re.search(
        r"\b(threshold|what should|how should|during the .* wait|per phase|total)\b",
        clarification_text,
        flags=re.IGNORECASE,
    ):
        return prompt_clause_answer

    sibling_groups = _collect_sibling_groups(user_input, entities)
    if not sibling_groups:
        return _build_domain_auto_answer(
            user_input,
            clarifying_questions,
            entities,
            prompt_clause_answer,
        )

    group_clause_mappings = _build_group_clause_mappings(user_input, entities)
    wants_sensor = "sensor" in clarification_text
    explicitly_matched_groups = [
        group
        for group in sibling_groups
        if any(
            (
                _normalize_phrase(entity.get("entity_id")) in clarification_text
                or _normalize_phrase(entity.get("name")) in clarification_text
                or _normalize_phrase(_sibling_group_label(group)) in clarification_text
            )
            for entity in group
        )
    ]
    matched_groups = (
        explicitly_matched_groups
        if explicitly_matched_groups
        else [
            group
            for group in sibling_groups
            if wants_sensor
            and all(str(entity.get("domain") or "") == "sensor" for entity in group)
        ]
    )

    if not matched_groups:
        return _build_domain_auto_answer(
            user_input,
            clarifying_questions,
            entities,
            prompt_clause_answer,
        )

    obvious_singles = [
        entity
        for entity in _find_obvious_named_entities(user_input, entities or [], 20)
        if not any(
            candidate.get("entity_id") == entity.get("entity_id")
            for group in matched_groups
            for candidate in group
        )
    ]
    include_broader_hints = not explicitly_matched_groups
    automation_matches = [
        entity
        for entity in _relevant_domain_matches(user_input, entities or [], "automation", 2, 8)
        if not any(
            candidate.get("entity_id") == entity.get("entity_id")
            for candidate in obvious_singles
        )
    ]
    notify_matches = _relevant_domain_matches(
        user_input, entities or [], "notify", 1, 4
    )

    group_hints = "; ".join(
        f"{_sibling_group_label(group)} -> "
        + ", ".join(entity["entity_id"] for entity in group)
        for group in matched_groups
    )
    clause_hints = "; ".join(
        f"{mapping['label']} -> "
        + ", ".join(str(entity_id) for entity_id in mapping["entities"])
        + f' for "{mapping["clause"]}"'
        for mapping in group_clause_mappings
        if any(_sibling_group_label(group) == mapping["label"] for group in matched_groups)
    )
    single_hints = (
        " Use these exact single-entity matches as already resolved too: "
        + "; ".join(
            f"{entity['name']} -> {entity['entity_id']}"
            for entity in obvious_singles
        )
        + "."
        if include_broader_hints and obvious_singles
        else ""
    )
    automation_hints = (
        " Use all matching automation guard entities together too: "
        + "; ".join(
            f"{entity['name']} -> {entity['entity_id']}"
            for entity in automation_matches
        )
        + "."
        if include_broader_hints and len(automation_matches) > 1
        else ""
    )
    notification_hints = (
        " Use the matching notification target too: "
        + "; ".join(
            f"{entity['name']} -> {entity['entity_id']}"
            for entity in notify_matches[:2]
        )
        + "."
        if include_broader_hints and notify_matches
        else ""
    )
    clause_mapping_hints = (
        " Apply these grouped families to their matching clauses too: "
        + clause_hints
        + "."
        if clause_hints
        else ""
    )
    group_answer = (
        "Use all matching entities in these sibling sets together, not a single entity: "
        f"{group_hints}.{clause_mapping_hints}{single_hints}{automation_hints}"
        f"{notification_hints} Do not ask which single entity to use. Continue and return the automation JSON."
    )

    domain_answer = _build_domain_auto_answer(
        user_input,
        clarifying_questions,
        entities,
        "",
    )
    if domain_answer:
        group_answer = f"{group_answer} {domain_answer}"

    if prompt_clause_answer:
        return f"{group_answer} {prompt_clause_answer}"
    return group_answer


def _build_domain_auto_answer(
    user_input: str,
    clarifying_questions: list[str],
    entities: list[dict[str, str]] | None,
    prompt_clause_answer: str,
) -> str:
    """Answer domain-level clarification questions when the prompt already resolves them."""
    entities = entities or []
    if not clarifying_questions or not entities:
        return prompt_clause_answer

    clarification_text = _normalize_phrase(" ".join(clarifying_questions))
    answers: list[str] = []

    if re.search(r"\b(automation|guard|active|inactive)\b", clarification_text):
        automation_matches = _relevant_domain_matches(
            user_input, entities, "automation", 2, 8
        )
        if automation_matches:
            answers.append(
                "Use these matching automation guard entities together: "
                + "; ".join(
                    f"{entity['name']} -> {entity['entity_id']}"
                    for entity in automation_matches[:4]
                )
                + "."
            )

    if re.search(
        r"\b(notify|notification|iphone|phone|mobile|message)\b",
        clarification_text,
    ):
        notify_matches = _relevant_domain_matches(
            user_input, entities, "notify", 1, 4
        )
        if notify_matches:
            answers.append(
                "Use the matching notification target: "
                + "; ".join(
                    f"{entity['name']} -> {entity['entity_id']}"
                    for entity in notify_matches[:2]
                )
                + "."
            )

    domain_answer = (
        " ".join(answers)
        + " Continue and return the automation JSON."
        if answers
        else ""
    )
    if prompt_clause_answer and domain_answer:
        return f"{domain_answer} {prompt_clause_answer}"
    return domain_answer or prompt_clause_answer


def build_prompt(
    user_input: str,
    entity_summary: str,
    entities: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Construct the OpenAI-compatible messages array for automation generation.

    Args:
        user_input: The user's natural-language automation description.
        entity_summary: The formatted entity list string from entity_collector.

    Returns:
        A list of message dicts with 'role' and 'content' keys.
    """
    guidance_lines = _build_prompt_guidance(user_input, entities)
    formatted_entity_summary = entity_summary
    entity_map_block = ""
    if entities:
        compact_summary = "\n".join(
            f"{entity['entity_id']} ({entity['name']})"
            for entity in entities
            if entity.get("entity_id") and entity.get("name")
        )
        if compact_summary:
            formatted_entity_summary = compact_summary
        entity_map = build_entity_resolution_map(user_input, entities)
        if entity_map:
            map_lines: list[str] = []
            for label, payload in entity_map.items():
                entity_ids = ", ".join(payload.get("entity_ids", []) or [])
                role = str(payload.get("role") or "").strip()
                notes: list[str] = []
                if role:
                    notes.append(role.replace("_", " "))
                if payload.get("required_state"):
                    notes.append(f'must be "{payload["required_state"]}" to proceed')
                elif payload.get("blocked_state"):
                    notes.append(f'blocked when "{payload["blocked_state"]}"')
                colour_request = payload.get("colour_request") or {}
                if colour_request:
                    colour_bits = []
                    if colour_request.get("color_temp"):
                        colour_bits.append(f"color_temp {colour_request['color_temp']}")
                    if colour_request.get("color_name"):
                        colour_bits.append(f"color {colour_request['color_name']}")
                    if colour_request.get("brightness_pct"):
                        colour_bits.append(
                            f"brightness {colour_request['brightness_pct']}%"
                        )
                    if colour_bits:
                        notes.append(", ".join(colour_bits))
                note_text = f" [{'; '.join(notes)}]" if notes else ""
                map_lines.append(f'- "{label}" -> {entity_ids}{note_text}')
            entity_map_block = (
                "ENTITY MAP (use these exact IDs, do not invent others):\n"
                + "\n".join(map_lines)
                + "\n\n"
            )
    guidance_block = (
        "\n\nPrompt-specific guidance:\n- " + "\n- ".join(guidance_lines)
        if guidance_lines
        else ""
    )
    user_message = (
        f"{entity_map_block}Available entities:\n{formatted_entity_summary}"
        f"{guidance_block}\n\n"
        f"Create an automation for:\n{user_input}"
    )

    messages = [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    _LOGGER.debug(
        "Built prompt: system=%d chars, user=%d chars",
        len(INTENT_SYSTEM_PROMPT),
        len(user_message),
    )

    return messages
