"""Collect and format Home Assistant entities for LLM context."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import PRIORITY_DOMAINS

_LOGGER = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GROUP_MARKER_RE = re.compile(
    r"\b(all|both|three|every|each|single phase|phase|phases|zones|channels|outputs|inputs)\b"
)
_VARIANT_SUFFIX_RE = re.compile(
    r"_(?:l\d+|phase_?\d+|\d+|left|right|rear|front|north|south|east|west|upstairs|downstairs)$"
)
_NAME_VARIANT_SUFFIX_RE = re.compile(
    r"(?:\s+(?:l\d+|phase\s*\d+|\d+|left|right|rear|front|north|south|east|west|upstairs|downstairs))$"
)
_IGNORE_TOKENS = {
    "a",
    "an",
    "and",
    "at",
    "automation",
    "create",
    "for",
    "if",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "please",
    "the",
    "then",
    "to",
    "turn",
    "when",
    "with",
}
_IMPORTANT_SHORT_TOKENS = {"tv", "ac"}
_AUTOMATION_MATCH_IGNORE_TOKENS = {
    "active",
    "already",
    "disable",
    "disabled",
    "enable",
    "enabled",
    "off",
    "run",
    "running",
    "start",
    "started",
    "stop",
    "stopped",
    "switch",
}
_SEMANTIC_CONTEXT_IGNORE_TOKENS = {
    "above",
    "after",
    "all",
    "already",
    "any",
    "before",
    "below",
    "between",
    "both",
    "delay",
    "drops",
    "each",
    "every",
    "exceeds",
    "flash",
    "monitor",
    "not",
    "only",
    "single",
    "still",
    "than",
    "total",
    "triggered",
    "wait",
    "warning",
    "weekday",
    "weekdays",
    "whichever",
    "while",
}
_DOMAIN_PHRASE_IGNORE_TOKENS: dict[str, set[str]] = {
    "automation": {
        "active",
        "already",
        "any",
        "automation",
        "currently",
        "disabled",
        "enabled",
        "if",
        "not",
        "off",
        "on",
        "run",
        "running",
        "that",
        "the",
        "these",
        "this",
        "those",
        "unless",
        "when",
        "while",
    },
    "notify": {
        "alert",
        "message",
        "notification",
        "notify",
        "saying",
        "send",
        "service",
        "target",
        "through",
        "to",
        "via",
        "with",
    },
}
_SEMANTIC_PROMPT_HINTS: tuple[dict[str, Any], ...] = (
    {
        "label": "power",
        "pattern": re.compile(r"\b(power|watt(?:age|s)?|kw|kilowatt(?:s)?)\b"),
        "domains": {"sensor", "number", "input_number"},
        "device_classes": {"power", "energy"},
        "tokens": {"power", "watt", "wattage", "kw", "kilowatt", "energy"},
        "require_affinity_match": True,
    },
    {
        "label": "voltage",
        "pattern": re.compile(r"\b(voltage|volt(?:s)?)\b"),
        "domains": {"sensor", "number", "input_number"},
        "device_classes": {"voltage"},
        "tokens": {"voltage", "volt", "volts"},
        "require_affinity_match": True,
    },
    {
        "label": "current",
        "pattern": re.compile(r"\b(current|amp(?:s|ere|erage)?|amperage)\b"),
        "domains": {"sensor", "number", "input_number"},
        "device_classes": {"current"},
        "tokens": {"current", "amp", "amps", "ampere", "amperage"},
        "require_affinity_match": True,
    },
    {
        "label": "notification",
        "pattern": re.compile(r"\b(notify|notification|iphone|phone|mobile)\b"),
        "domains": {"notify"},
        "device_classes": {"service"},
        "tokens": {"notify", "notification", "iphone", "phone", "mobile", "app"},
        "prefer_domain_matches": True,
    },
    {
        "label": "tv",
        "pattern": re.compile(r"\b(tv|television)\b"),
        "domains": {"media_player"},
        "device_classes": set(),
        "tokens": {"tv", "television"},
        "exclude_speaker_like": True,
    },
)
_SPEAKER_LIKE_RE = re.compile(r"\b(speaker|speakers|homepod|audio|sonos|nestaudio)\b")


def _tokenize(text: str) -> list[str]:
    """Tokenize prompt or entity text while preserving useful short tokens."""
    return [
        token
        for token in _TOKEN_RE.findall(str(text or "").lower())
        if (len(token) >= 3 or token in _IMPORTANT_SHORT_TOKENS)
        and token not in _IGNORE_TOKENS
    ]


def _normalize_phrase(text: str) -> str:
    """Normalize a phrase for loose entity-name matching."""
    return " ".join(str(text or "").lower().replace("_", " ").split())


def _entity_haystack(entity: dict[str, Any]) -> str:
    """Build a normalized haystack string for semantic matching."""
    return _normalize_phrase(
        " ".join(
            str(entity.get(field) or "")
            for field in ("entity_id", "name", "domain", "device_class", "state")
        )
    )


def _is_speaker_like(entity: dict[str, Any]) -> bool:
    """Return True when a media player is more likely to be a speaker than a TV."""
    device_class = _normalize_phrase(entity.get("device_class"))
    if device_class == "speaker":
        return True
    return bool(_SPEAKER_LIKE_RE.search(_entity_haystack(entity)))


def _find_obvious_named_entities(
    user_input: str,
    entities: list[dict[str, Any]],
    max_matches: int = 12,
) -> list[dict[str, Any]]:
    """Return multi-word entity names that are strongly implied by the prompt."""
    normalized_prompt = _normalize_phrase(user_input)
    if not normalized_prompt or not entities:
        return []

    prompt_tokens = set(_tokenize(user_input))
    scored: list[tuple[int, int, dict[str, Any]]] = []

    for index, entity in enumerate(entities):
        raw_name = str(entity.get("name") or "").strip()
        if not raw_name:
            continue

        normalized_name = raw_name.lower()
        base_name = _NAME_VARIANT_SUFFIX_RE.sub("", normalized_name).strip()
        name_tokens = _tokenize(raw_name)
        if not name_tokens:
            continue

        score = 0
        if len(name_tokens) >= 2 and normalized_name in normalized_prompt:
            score += 100
        if (
            base_name
            and base_name != normalized_name
            and len(base_name.split()) >= 2
            and base_name in normalized_prompt
        ):
            score += 70
        if len(name_tokens) == 1 and len(prompt_tokens) == 1 and name_tokens[0] in prompt_tokens:
            score += 80

        matched_tokens = [token for token in name_tokens if token in prompt_tokens]
        if len(matched_tokens) == len(name_tokens) and len(name_tokens) >= 2:
            score += 80 + len(name_tokens)
        elif len(matched_tokens) >= 2:
            score += 20 + len(matched_tokens)
        if base_name and base_name != normalized_name:
            base_tokens = _tokenize(base_name)
            matched_base_tokens = [
                token for token in base_tokens if token in prompt_tokens
            ]
            if len(matched_base_tokens) == len(base_tokens) and len(base_tokens) >= 2:
                score += 50 + len(base_tokens)
            elif len(matched_base_tokens) >= 2:
                score += 16 + len(matched_base_tokens)

        if score > 0:
            scored.append((score, index, entity))

    scored.sort(key=lambda item: (-item[0], item[1]))

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for _score, _index, entity in scored[:max_matches]:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id or entity_id in seen_ids:
            continue
        selected.append(entity)
        seen_ids.add(entity_id)

    return selected


def _clean_domain_phrase(phrase: str, domain: str) -> str:
    """Normalize a captured domain phrase and strip glue words."""
    ignored_tokens = _DOMAIN_PHRASE_IGNORE_TOKENS.get(domain, set())
    tokens = [
        token for token in _tokenize(phrase) if token not in ignored_tokens
    ]
    return " ".join(tokens)


def _collect_semantic_prompt_matches(
    user_input: str,
    entities: list[dict[str, Any]],
    max_matches_per_hint: int = 4,
) -> list[dict[str, Any]]:
    """Infer relevant entity families from semantic measurement wording."""
    normalized_prompt = _normalize_phrase(user_input)
    if not normalized_prompt or not entities:
        return []

    prompt_tokens = set(_tokenize(user_input))
    active_hints = [
        hint
        for hint in _SEMANTIC_PROMPT_HINTS
        if hint["pattern"].search(normalized_prompt)
    ]
    if not active_hints:
        return []

    prompt_has_output = "output" in prompt_tokens
    prompt_has_input = "input" in prompt_tokens
    results: list[dict[str, Any]] = []
    for hint in active_hints:
        preferred_domains = set(hint.get("domains", set()))
        preferred_present = bool(
            hint.get("prefer_domain_matches")
            and any(
                str(entity.get("domain") or "") in preferred_domains
                for entity in entities
            )
        )
        context_tokens = {
            token
            for token in prompt_tokens - set(hint.get("tokens", set()))
            if token not in _SEMANTIC_CONTEXT_IGNORE_TOKENS
        }
        scored: list[dict[str, Any]] = []
        for index, entity in enumerate(entities):
            domain = str(entity.get("domain") or "")
            device_class = _normalize_phrase(entity.get("device_class"))
            haystack = _entity_haystack(entity)
            haystack_tokens = set(_tokenize(haystack))

            if preferred_present and domain not in preferred_domains:
                continue
            if hint.get("exclude_speaker_like") and _is_speaker_like(entity):
                continue

            score = 0
            context_overlap = 0
            if domain in hint["domains"]:
                score += 3
            if device_class in hint["device_classes"]:
                score += 5

            matched_tokens = len(haystack_tokens & hint["tokens"])
            if (
                hint.get("require_affinity_match")
                and matched_tokens == 0
                and device_class not in hint["device_classes"]
            ):
                continue
            score += matched_tokens * 2
            context_overlap = len(haystack_tokens & context_tokens)
            score += context_overlap * 2

            matches_specific_scope = (
                (prompt_has_output and "output" in haystack_tokens)
                or (prompt_has_input and "input" in haystack_tokens)
            )
            if (
                prompt_has_output
                and "input" in haystack_tokens
                and "output" not in haystack_tokens
            ):
                score -= 4
            if (
                prompt_has_input
                and "output" in haystack_tokens
                and "input" not in haystack_tokens
            ):
                score -= 4

            if domain == "notify" and hint["label"] == "notification":
                score += 5
            if domain == "media_player" and hint["label"] == "tv":
                score += 2

            if score > 0:
                scored.append(
                    {
                        "score": score,
                        "index": index,
                        "entity": entity,
                        "context_overlap": context_overlap,
                        "matches_specific_scope": matches_specific_scope,
                    }
                )

        scored.sort(key=lambda item: (-item["score"], item["index"]))
        filtered = scored
        if any(item["matches_specific_scope"] for item in filtered):
            filtered = [
                item for item in filtered if item["matches_specific_scope"]
            ]
        if (
            any(item["context_overlap"] > 0 for item in filtered)
            and (
                hint.get("require_affinity_match")
                or hint.get("prefer_domain_matches")
            )
        ):
            filtered = [
                item for item in filtered if item["context_overlap"] > 0
            ]
        best_score = filtered[0]["score"] if filtered else 0
        if best_score > 0 and hint.get("require_affinity_match"):
            filtered = [
                item
                for item in filtered
                if item["score"] >= max(5, best_score - 4)
            ]
        selected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in filtered[:max_matches_per_hint]:
            entity = item["entity"]
            entity_id = str(entity.get("entity_id") or "")
            if not entity_id or entity_id in seen_ids:
                continue
            selected.append(entity)
            seen_ids.add(entity_id)

        if selected:
            results.append({"label": hint["label"], "entities": selected})

    return results


def _semantic_entity_matches(
    user_input: str,
    entities: list[dict[str, Any]],
    max_matches: int = 16,
) -> list[dict[str, Any]]:
    """Flatten semantic prompt matches into a unique entity list."""
    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for match in _collect_semantic_prompt_matches(user_input, entities):
        for entity in match["entities"]:
            entity_id = str(entity.get("entity_id") or "")
            if not entity_id or entity_id in seen_ids:
                continue
            selected.append(entity)
            seen_ids.add(entity_id)
            if len(selected) >= max_matches:
                return selected

    return selected


def _variant_stem(entity_id: str) -> str:
    """Return a canonical entity stem for sibling expansion."""
    normalized = str(entity_id or "").lower()
    return _VARIANT_SUFFIX_RE.sub("", normalized)


def _expand_variant_entities(
    user_input: str,
    entities: list[dict[str, Any]],
    seed_entities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand relevant sibling variants when the prompt implies a full set."""
    if not _GROUP_MARKER_RE.search(str(user_input or "")):
        return []
    if not entities or not seed_entities:
        return []

    grouped: dict[str, list[dict[str, Any]]] = {}
    for entity in entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id:
            continue
        grouped.setdefault(_variant_stem(entity_id), []).append(entity)

    expanded: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entity in seed_entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id:
            continue
        siblings = grouped.get(_variant_stem(entity_id), [])
        if len(siblings) < 2:
            continue
        for sibling in siblings:
            sibling_id = str(sibling.get("entity_id") or "")
            if not sibling_id or sibling_id in seen_ids:
                continue
            expanded.append(sibling)
            seen_ids.add(sibling_id)

    return expanded


def _extract_domain_phrases(user_input: str, domain: str) -> list[str]:
    """Extract domain-specific concept phrases from the user prompt."""
    normalized = _normalize_phrase(user_input)
    if not normalized:
        return []

    if domain == "automation":
        phrases: list[str] = []
        pattern = re.compile(
            r"\b(?:the\s+)?([a-z0-9 ]{3,80}?)\s+automation\b(?:\s+is\b|\s+are\b|\s+was\b|\s+were\b|\s+already\b|\s+currently\b|[.,]|$)"
        )
        for match in pattern.finditer(normalized):
            phrase = _clean_domain_phrase(match.group(1), domain)
            if phrase:
                phrases.append(phrase)
        return list(dict.fromkeys(phrases))

    if domain == "notify":
        phrases: list[str] = []
        patterns = (
            re.compile(
                r"\b(?:send\s+)?(?:a\s+)?(?:notification|notify|message|alert)\s+(?:to\s+)?(?:my\s+)?([a-z0-9 ]{2,60}?)(?:\s+saying\b|\s+that\b|[.,]|$)"
            ),
            re.compile(
                r"\b(?:to|for)\s+my\s+([a-z0-9 ]{2,60}?)(?:\s+saying\b|\s+that\b|[.,]|$)"
            ),
        )
        for pattern in patterns:
            for match in pattern.finditer(normalized):
                phrase = _clean_domain_phrase(match.group(1), domain)
                if phrase:
                    phrases.append(phrase)
        return list(dict.fromkeys(phrases))

    return []


def _relevant_domain_matches(
    user_input: str,
    entities: list[dict[str, Any]],
    domain: str,
    min_matched_tokens: int = 2,
    max_matches: int = 8,
) -> list[dict[str, Any]]:
    """Find prompt-relevant entities within a specific domain."""
    if not entities:
        return []

    domain_phrases = _extract_domain_phrases(user_input, domain)
    if domain_phrases:
        matched_by_phrase: list[tuple[int, int, dict[str, Any]]] = []
        for index, entity in enumerate(entities):
            if str(entity.get("domain") or "") != domain:
                continue
            haystack = _normalize_phrase(
                f"{entity.get('entity_id') or ''} {entity.get('name') or ''}"
            )
            for phrase in domain_phrases:
                if phrase and phrase in haystack:
                    matched_by_phrase.append((len(_tokenize(phrase)), index, entity))
                    break
        matched_by_phrase.sort(key=lambda item: (-item[0], item[1]))
        phrase_selected: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for _score, _index, entity in matched_by_phrase[:max_matches]:
            entity_id = str(entity.get("entity_id") or "")
            if not entity_id or entity_id in seen_ids:
                continue
            phrase_selected.append(entity)
            seen_ids.add(entity_id)
        if phrase_selected:
            return phrase_selected

    prompt_tokens = set(_tokenize(user_input))
    if not prompt_tokens:
        return []

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for index, entity in enumerate(entities):
        if str(entity.get("domain") or "") != domain:
            continue
        haystack_tokens = set(
            _tokenize(f"{entity.get('entity_id') or ''} {entity.get('name') or ''}")
        )
        matched = sum(
            1
            for token in haystack_tokens
            if token in prompt_tokens
            and not (
                domain == "automation" and token in _AUTOMATION_MATCH_IGNORE_TOKENS
            )
        )
        if matched < min_matched_tokens:
            continue
        scored.append((matched, index, entity))

    scored.sort(key=lambda item: (-item[0], item[1]))

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for _score, _index, entity in scored[:max_matches]:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id or entity_id in seen_ids:
            continue
        selected.append(entity)
        seen_ids.add(entity_id)

    return selected


def _humanize_service_name(service_name: str) -> str:
    """Return a readable label for a Home Assistant service name."""
    cleaned = str(service_name or "").strip().replace(".", "_")
    if not cleaned:
        return "Notify"

    parts = [part for part in cleaned.split("_") if part]
    if cleaned.startswith("mobile_app_") and len(parts) > 2:
        device_name = " ".join(part.capitalize() for part in parts[2:])
        return f"Notify {device_name}"
    return " ".join(part.capitalize() for part in parts)


def _notification_service_entries(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return notify services as pseudo-entities for prompt context."""
    services = hass.services.async_services()
    notify_services = services.get("notify", {})
    entries: list[dict[str, Any]] = []

    for service_name in sorted(notify_services):
        if not service_name:
            continue
        entries.append(
            {
                "entity_id": f"notify.{service_name}",
                "name": _humanize_service_name(service_name),
                "domain": "notify",
                "state": "service",
                "device_class": "service",
            }
        )

    return entries


async def get_entity_context(
    hass: HomeAssistant, max_entities: int = 0
) -> list[dict[str, Any]]:
    """Pull entities from the registry and return a prioritised list.

    Args:
        max_entities: Maximum entities to return. 0 means all entities.

    Returns a list of dicts with keys:
        entity_id, name, domain, state, device_class
    """
    registry = er.async_get(hass)
    entities: list[dict[str, Any]] = []

    for entry in registry.entities.values():
        if entry.disabled_by is not None:
            continue

        domain = entry.domain
        state_obj = hass.states.get(entry.entity_id)
        state_value = state_obj.state if state_obj else "unknown"
        friendly_name = (
            entry.name
            or entry.original_name
            or (state_obj.attributes.get("friendly_name") if state_obj else None)
            or entry.entity_id
        )
        device_class = (
            entry.device_class
            or entry.original_device_class
            or (state_obj.attributes.get("device_class") if state_obj else None)
        )

        entities.append(
            {
                "entity_id": entry.entity_id,
                "name": friendly_name,
                "domain": domain,
                "state": state_value,
                "device_class": device_class,
            }
        )

    entities.extend(_notification_service_entries(hass))

    # Build priority index (lower = higher priority)
    priority_index = {d: i for i, d in enumerate(PRIORITY_DOMAINS)}
    fallback_priority = len(PRIORITY_DOMAINS)

    # Sort: priority domains first, then alphabetically by domain, then by name
    entities.sort(
        key=lambda e: (
            priority_index.get(e["domain"], fallback_priority),
            e["domain"],
            e["name"],
        )
    )

    truncated = entities[:max_entities] if max_entities > 0 else entities
    _LOGGER.debug(
        "Entity collector: %d total, returning %d (limit %s)",
        len(entities),
        len(truncated),
        max_entities or "all",
    )
    return truncated


async def get_entity_summary_string(
    hass: HomeAssistant, max_entities: int = 0
) -> str:
    """Return a compact string of entities for injection into the LLM prompt.

    Format: one entity per line: `light.living_room_lamp (Living Room Lamp) [on]`
    """
    entities = await get_entity_context(hass, max_entities)
    lines: list[str] = []
    for e in entities:
        lines.append(f"{e['entity_id']} ({e['name']}) [{e['state']}]")
    return "\n".join(lines)


def select_relevant_entities(
    user_input: str,
    entities: list[dict[str, Any]],
    max_entities: int,
    fallback_entities: int = 6,
) -> list[dict[str, Any]]:
    """Select the most prompt-relevant entities plus a small fallback set."""
    if max_entities <= 0 or len(entities) <= max_entities:
        return entities

    tokens = [
        token for token in _tokenize(str(user_input or "").lower())
    ]
    if not tokens:
        return entities[:max_entities]

    scored: list[tuple[int, int, dict[str, Any]]] = []
    obvious_entities = _find_obvious_named_entities(user_input, entities)
    semantic_entities = _semantic_entity_matches(user_input, entities)
    automation_matches = (
        _relevant_domain_matches(user_input, entities, "automation")
        if "automation" in _normalize_phrase(user_input)
        else []
    )
    notify_matches = (
        _relevant_domain_matches(user_input, entities, "notify", 1, 4)
        if re.search(r"\b(notify|notification|iphone|phone|mobile)\b", _normalize_phrase(user_input))
        else []
    )
    expanded_entities = _expand_variant_entities(
        user_input,
        entities,
        [
            *obvious_entities,
            *notify_matches,
            *semantic_entities,
            *automation_matches,
        ],
    )

    for index, entity in enumerate(entities):
        haystack = " ".join(
            str(
                entity.get(field) or ""
            ).replace("_", " ")
            for field in ("entity_id", "name", "domain", "device_class", "state")
        ).lower()

        score = 0
        for token in tokens:
            if token not in haystack:
                continue
            score += 2
            if token in str(entity.get("entity_id", "")).lower():
                score += 3
            if token in str(entity.get("name", "")).lower():
                score += 4

        if score > 0:
            scored.append((score, index, entity))

    scored.sort(key=lambda item: (-item[0], item[1]))

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for entity in [
        *obvious_entities,
        *notify_matches,
        *semantic_entities,
        *expanded_entities,
        *automation_matches,
    ]:
        if len(selected) >= min(max_entities, 18):
            break
        entity_id = str(entity.get("entity_id", ""))
        if entity_id in seen_ids:
            continue
        selected.append(entity)
        seen_ids.add(entity_id)

    relevant_limit = min(max_entities, 18)
    primary_limit = min(relevant_limit, max(1, max_entities - fallback_entities))
    primary_capacity = max(0, primary_limit - len(selected))
    for _score, _index, entity in scored[:primary_capacity]:
        entity_id = str(entity.get("entity_id", ""))
        if entity_id in seen_ids:
            continue
        selected.append(entity)
        seen_ids.add(entity_id)

    minimum_relevant = min(max_entities, 12)
    if len(selected) >= minimum_relevant:
        return selected[:relevant_limit]

    fallback_target = min(max_entities, max(len(selected), minimum_relevant))
    for entity in entities:
        if len(selected) >= fallback_target:
            break
        entity_id = str(entity.get("entity_id", ""))
        if entity_id in seen_ids:
            continue
        selected.append(entity)
        seen_ids.add(entity_id)

    return selected[:fallback_target]
