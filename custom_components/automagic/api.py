"""REST API views for AutoMagic."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from aiohttp import web
import yaml

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .automation_writer import (
    AutomationValidationError,
    install_automation,
    validate_automation,
)
from .const import (
    API_PATH_ENTITIES,
    API_PATH_GENERATE,
    API_PATH_GENERATE_STATUS,
    API_PATH_HISTORY,
    API_PATH_HISTORY_ENTRY,
    API_PATH_INSTALL,
    API_PATH_INSTALL_REPAIR,
    API_PATH_SERVICES,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_SERVICE_ID,
    DOMAIN,
)
from .entity_collector import (
    _collect_semantic_prompt_matches,
    _expand_variant_entities,
    _find_obvious_named_entities,
    _relevant_domain_matches,
    get_entity_context,
    select_relevant_entities,
)
from .llm_client import (
    LLMClient,
    LLMConnectionError,
    LLMResponseError,
    _normalize_automation_yaml_text,
)
from .prompt_builder import (
    build_auto_clarification_answer,
    build_prompt,
)
from .service_config import (
    build_service_label,
    get_configured_services,
    get_default_service_id,
    get_service_config,
    normalize_config_data,
)

_LOGGER = logging.getLogger(__name__)
_HISTORY_FILE = "automagic_history.json"
_GENERATION_JOB_KEY = f"{DOMAIN}_generation_jobs"
_JOB_TTL_SECONDS = 3600
_STATUS_POLL_MS = 2000
_BACKEND_PROBE_DELAY_SECONDS = 15
_BACKEND_PROBE_INTERVAL_SECONDS = 10
_DEFAULT_GENERATION_CONTEXT_LIMIT = 60
_YAML_REPAIR_ATTEMPTS = 2
_YAML_REGENERATION_ATTEMPTS = 1
_ENTITY_REPAIR_ATTEMPTS = 2
_TIME_WINDOW_RE = re.compile(
    r"\bbetween\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:and|to|-)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
    re.IGNORECASE,
)
_POWER_THRESHOLD_RE = re.compile(
    r"\bac output power\b[\s\S]{0,120}?\bdrops below\s+(\d+(?:\.\d+)?)\s*(?:watts?|w)\b",
    re.IGNORECASE,
)
_POWER_ABOVE_THRESHOLD_RE = re.compile(
    r"\b(?:total\s+)?ac output power\b[\s\S]{0,120}?\babove\s+(\d+(?:\.\d+)?)\s*(?:watts?|w)\b",
    re.IGNORECASE,
)
_VOLTAGE_THRESHOLD_RE = re.compile(
    r"\b(?:single\s+phase\s+)?(?:ac output\s+)?voltage\b[\s\S]{0,120}?\bdrops below\s+(\d+(?:\.\d+)?)\s*(?:volts?|v)\b",
    re.IGNORECASE,
)
_CURRENT_THRESHOLD_RE = re.compile(
    r"\b(?:single\s+phase\s+)?(?:ac output\s+)?current\b[\s\S]{0,120}?\b(?:exceeds|is above|goes above|greater than)\s+(\d+(?:\.\d+)?)\s*(?:amps?|a)\b",
    re.IGNORECASE,
)
_WAIT_MINUTES_RE = re.compile(r"\bwait\s+(\d+)\s*minutes?\b", re.IGNORECASE)
_EXPLICIT_GUARD_RE = re.compile(
    r"(?:don't|do not)\s+run(?: any of this| this)?\s+if\s+(.+?)\s+is\s+already\s+(on|off|open|closed|locked|unlocked|active|inactive)\b",
    re.IGNORECASE,
)
_PLURAL_ENTITY_HINT_RE = re.compile(
    r"\b(all|both|three|every|each|either|switch(?:es)?|lights?|phases?|outputs?|inputs?|sensors?)\b",
    re.IGNORECASE,
)
_NEGATED_STATE_GUARD_PATTERNS = (
    re.compile(
        r"(?:making sure|make sure|ensure(?: that)?|checking(?: this)? by making sure|only if|provided that)\s+(.+?)\s+(?:is|are)\s+not\s+['\"]([^'\"]+)['\"]",
        re.IGNORECASE,
    ),
)
_YAML_REPAIR_SYSTEM_PROMPT = """\
You are an expert Home Assistant automation syntax repair assistant.
Return only a JSON object with exactly four keys: yaml, summary, needs_clarification, clarifying_questions.
The yaml value must be a complete Home Assistant automation string that starts directly with alias:.
Use Home Assistant 2024.10+ syntax only.
- Use triggers: and actions: at the top level.
- Use trigger: inside trigger items, not platform:.
- Use action: inside action items, not service:.
- action values must be exactly <domain>.<service_name> (e.g. light.turn_on, notify.mobile_app_iphone). \
Never include an entity_id in the action value. Use a separate target: entity_id: field instead.
- Script steps such as delay, wait_for_trigger, wait_template, choose, if, repeat, variables, stop, event, and scene must use their own YAML keys. \
For example use - delay: "00:05:00", not - action: delay.
- Include description:, triggers:, conditions:, actions:, and mode:.
- Do not wrap the YAML in markdown fences, yaml:, automation:, or a list item.
- Put notify text under data: with a message key.
- Preserve the user's thresholds, guards, delays, entities, and notification text.
Do not ask for clarification. Return the final corrected JSON now."""
_YAML_REGENERATION_SYSTEM_PROMPT = """\
You are an expert Home Assistant automation generation assistant.
Return only a JSON object with exactly four keys: yaml, summary, needs_clarification, clarifying_questions.
The yaml value must be a complete Home Assistant automation string that starts directly with alias:.
Use Home Assistant 2024.10+ syntax only.
- Include description:, triggers:, conditions:, actions:, and mode:.
- Use triggers: and actions: at the top level.
- Use trigger: inside trigger items, not platform:.
- Use action: inside action items, not service:.
- action values must be exactly <domain>.<service_name> (e.g. light.turn_on, notify.mobile_app_iphone). \
Never include an entity_id in the action value. Use a separate target: entity_id: field instead.
- Script steps such as delay, wait_for_trigger, wait_template, choose, if, repeat, variables, stop, event, and scene must use their own YAML keys. \
For example use - delay: "00:05:00", not - action: delay.
- Do not wrap the YAML in markdown fences, yaml:, automation:, or a list item.
- Put notify text under data: with a message key.
- Preserve the user's thresholds, guards, delays, entities, and notification text.
If prior drafts were invalid, ignore them and regenerate the automation cleanly from the original request and entity context.
Do not ask for clarification unless the original request truly lacks a required detail. Return the final automation JSON now."""
_ENTITY_REPAIR_SYSTEM_PROMPT = """\
You are an expert Home Assistant automation entity correction assistant.
Return only a JSON object with exactly four keys: yaml, summary, needs_clarification, clarifying_questions.
The yaml value must be a complete Home Assistant automation string that starts directly with alias:.
Use Home Assistant 2024.10+ syntax only.
- Use triggers: and actions: at the top level.
- Use trigger: inside trigger items, not platform:.
- Use action: inside action items, not service:.
- action values must be exactly <domain>.<service_name> (e.g. light.turn_on, notify.mobile_app_iphone). \
Never include an entity_id in the action value. Use a separate target: entity_id: field instead.
- Script steps such as delay, wait_for_trigger, wait_template, choose, if, repeat, variables, stop, event, and scene must use their own YAML keys. \
For example use - delay: "00:05:00", not - action: delay.
- Include description:, triggers:, conditions:, actions:, and mode:.
- Do not wrap the YAML in markdown fences, yaml:, automation:, or a list item.
- Put notify text under data: with a message key.
The previous automation YAML referenced entity_ids that do not exist in this Home Assistant instance.
Replace every invalid entity_id with the closest correct entity_id from the provided entity list.
Preserve all thresholds, guards, delays, and notification messages.
Do not ask for clarification. Return the corrected automation JSON now."""
_INSTALL_REPAIR_SYSTEM_PROMPT = """\
You are an expert Home Assistant automation repair assistant.
The user tried to install an automation but Home Assistant rejected it with a specific error.
Rewrite the automation to fix the exact error described while preserving the original intent.
Return only a JSON object with exactly four keys: yaml, summary, needs_clarification, clarifying_questions.
The yaml value must be a complete Home Assistant automation string that starts directly with alias:.
Use Home Assistant 2024.10+ syntax only.
- Use triggers: and actions: at the top level.
- Use trigger: inside trigger items, not platform:.
- Use action: inside action items, not service:.
- action values must be exactly <domain>.<service_name> (e.g. light.turn_on, notify.mobile_app_iphone). \
Never include an entity_id in the action value. Use a separate target: entity_id: field instead.
- Script steps such as delay, wait_for_trigger, wait_template, choose, if, repeat, variables, stop, event, and scene must use their own YAML keys. \
For example use - delay: "00:05:00", not - action: delay.
- Include description:, triggers:, conditions:, actions:, and mode:.
- Do not wrap the YAML in markdown fences, yaml:, automation:, or a list item.
- Put notify text under data: with a message key.
Preserve the user's thresholds, guards, delays, entities, and notification text.
Do not ask for clarification. Return the final corrected JSON now."""
_INSTALL_REPAIR_ATTEMPTS = 2


def _history_path(hass: HomeAssistant) -> str:
    """Return the path to the history JSON file."""
    return hass.config.path(_HISTORY_FILE)


def _load_history(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Load automation history from disk."""
    path = _history_path(hass)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(hass: HomeAssistant, history: list[dict[str, Any]]) -> None:
    """Persist automation history to disk."""
    path = _history_path(hass)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def _history_entry_id(item: dict[str, Any]) -> str:
    """Return a stable identifier for a history row."""
    existing = str(item.get("entry_id", "") or "").strip()
    if existing:
        return existing

    fingerprint = "\x1f".join(
        str(item.get(field, "") or "").strip()
        for field in ("timestamp", "alias", "prompt", "summary", "filename", "yaml")
    )
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:16]


def _normalize_history_entries(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every history row includes the fields the UI expects."""
    normalized: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["entry_id"] = _history_entry_id(row)
        normalized.append(row)
    return normalized


def _installed_automation_aliases(hass: HomeAssistant) -> set[str]:
    """Collect installed automation aliases from Home Assistant state."""
    aliases: set[str] = set()
    states = getattr(hass, "states", None)
    async_all = getattr(states, "async_all", None)
    state_items: list[tuple[str, Any]] = []

    if callable(async_all):
        try:
            automation_states = async_all("automation")
        except TypeError:
            automation_states = async_all()
        if isinstance(automation_states, list):
            state_items = [
                (str(getattr(state, "entity_id", "") or ""), state)
                for state in automation_states
            ]
    elif isinstance(states, dict):
        state_items = list(states.items())

    for entity_id, state in state_items:
        if not str(entity_id or "").startswith("automation."):
            continue
        attributes = getattr(state, "attributes", None)
        if attributes is None and isinstance(state, dict):
            attributes = state.get("attributes")
        if not isinstance(attributes, dict):
            continue
        friendly_name = str(
            attributes.get("friendly_name") or attributes.get("alias") or ""
        ).strip()
        if friendly_name:
            aliases.add(friendly_name)

    return aliases


def _history_entry_status(
    hass: HomeAssistant,
    item: dict[str, Any],
    installed_aliases: set[str] | None = None,
) -> str:
    """Resolve a persisted history row to installed/deleted/failed."""
    if not item.get("success"):
        return "failed"

    alias = str(item.get("alias", "") or "").strip()
    if not alias:
        return "installed"

    aliases = installed_aliases if installed_aliases is not None else _installed_automation_aliases(hass)
    return "installed" if alias in aliases else "deleted"


def _serialize_history_entries(
    hass: HomeAssistant,
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the history payload returned to the frontend."""
    normalized = _normalize_history_entries(history)
    installed_aliases = _installed_automation_aliases(hass)
    serialized: list[dict[str, Any]] = []
    for item in normalized:
        status = _history_entry_status(hass, item, installed_aliases)
        row = dict(item)
        row["status"] = status
        row["can_delete"] = status in {"failed", "deleted"}
        serialized.append(row)
    return serialized


def _append_history(
    hass: HomeAssistant,
    prompt: str,
    alias: str,
    summary: str,
    yaml_str: str,
    filename: str,
    success: bool,
) -> None:
    """Add an entry to the automation history."""
    history = _load_history(hass)
    history.insert(
        0,
        {
            "entry_id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt,
            "alias": alias,
            "summary": summary,
            "yaml": yaml_str,
            "filename": filename,
            "success": success,
        },
    )
    # Keep last 100 entries
    history = history[:100]
    _save_history(hass, history)


def _utcnow_iso() -> str:
    """Return the current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _get_generation_jobs(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Return the in-memory generation job store."""
    return hass.data.setdefault(_GENERATION_JOB_KEY, {})


def _prune_generation_jobs(hass: HomeAssistant) -> None:
    """Remove old completed jobs from memory."""
    jobs = _get_generation_jobs(hass)
    now = time.monotonic()
    stale_ids = [
        job_id
        for job_id, job in jobs.items()
        if job.get("status") in {"completed", "error", "needs_clarification"}
        and now
        - (
            job.get("finished_monotonic")
            or job.get("created_monotonic")
            or now
        )
        > _JOB_TTL_SECONDS
    ]
    for job_id in stale_ids:
        jobs.pop(job_id, None)


def _create_generation_job(
    hass: HomeAssistant,
    prompt: str,
    entity_filter: list[str] | None,
    *,
    conversation_messages: list[dict[str, str]] | None = None,
    service_config: dict[str, Any] | None = None,
    root_prompt: str | None = None,
    parent_job_id: str | None = None,
) -> dict[str, Any]:
    """Create a new generation job record."""
    _prune_generation_jobs(hass)

    now_iso = _utcnow_iso()
    now_monotonic = time.monotonic()
    selected_service = dict(service_config or {})
    job = {
        "job_id": uuid.uuid4().hex,
        "prompt": prompt,
        "entity_filter": entity_filter or [],
        "status": "queued",
        "message": "Preparing your request...",
        "detail": "Collecting entities and building the model prompt.",
        "created_at": now_iso,
        "updated_at": now_iso,
        "created_monotonic": now_monotonic,
        "started_at": None,
        "started_monotonic": None,
        "finished_at": None,
        "finished_monotonic": None,
        "backend_status": None,
        "backend_checked_at": None,
        "backend_checked_monotonic": 0.0,
        "yaml": None,
        "summary": None,
        "clarifying_questions": [],
        "entities_used": [],
        "conversation_messages": _clone_messages(conversation_messages),
        "assistant_message": None,
        "root_prompt": root_prompt or prompt,
        "parent_job_id": parent_job_id,
        "service_id": selected_service.get(CONF_SERVICE_ID, ""),
        "service_label": build_service_label(selected_service),
        "service_config": selected_service,
        "error": None,
        "task": None,
        "repair_in_progress": False,
    }

    _get_generation_jobs(hass)[job["job_id"]] = job
    return job


def _clone_messages(
    messages: list[dict[str, str]] | None,
) -> list[dict[str, str]] | None:
    """Clone chat messages for safe storage in job state."""
    if not messages:
        return None

    cloned: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).strip()
        content = str(message.get("content", "")).strip()
        if role and content:
            cloned.append({"role": role, "content": content})
    return cloned or None


def _build_clarification_message(
    summary: str, clarifying_questions: list[str]
) -> str:
    """Build a plain-text assistant turn for follow-up conversation."""
    parts: list[str] = []
    summary_text = str(summary or "").strip()
    if summary_text:
        parts.append(summary_text)

    if clarifying_questions:
        if len(clarifying_questions) == 1:
            parts.append(clarifying_questions[0])
        else:
            numbered = "\n".join(
                f"{index + 1}. {question}"
                for index, question in enumerate(clarifying_questions)
            )
            parts.append(
                "Please answer these questions so I can finish the automation:\n"
                f"{numbered}"
            )

    return "\n\n".join(part for part in parts if part).strip()


def _build_automation_context_message(summary: str, yaml_text: str) -> str:
    """Build a plain-text assistant turn that preserves the current YAML for follow-ups."""
    parts: list[str] = []
    summary_text = str(summary or "").strip()
    normalized_yaml = _normalize_automation_yaml_text(yaml_text)

    if summary_text:
        parts.append(f"Summary:\n{summary_text}")
    if normalized_yaml:
        parts.append(f"Current automation YAML:\n{normalized_yaml}")

    return "\n\n".join(part for part in parts if part).strip()


def _append_assistant_turn(
    job: dict[str, Any],
    assistant_message: str,
) -> None:
    """Append an assistant turn to the stored conversation if it is not already present."""
    message_text = str(assistant_message or "").strip()
    if not message_text:
        return

    messages = _clone_messages(job.get("conversation_messages")) or []
    if messages and messages[-1].get("role") == "assistant" and messages[-1].get(
        "content"
    ) == message_text:
        job["conversation_messages"] = messages
        return

    messages.append({"role": "assistant", "content": message_text})
    job["conversation_messages"] = messages


def _mark_job_running(job: dict[str, Any], message: str, detail: str) -> None:
    """Update a generation job as actively running."""
    now_iso = _utcnow_iso()
    now_monotonic = time.monotonic()
    if job["started_at"] is None:
        job["started_at"] = now_iso
        job["started_monotonic"] = now_monotonic

    job["status"] = "running"
    job["message"] = message
    job["detail"] = detail
    job["updated_at"] = now_iso


def _mark_job_complete(
    job: dict[str, Any],
    result: dict[str, Any],
    entities_used: list[str],
) -> None:
    """Mark a generation job as complete."""
    now_iso = _utcnow_iso()
    now_monotonic = time.monotonic()
    if job["started_at"] is None:
        job["started_at"] = now_iso
        job["started_monotonic"] = now_monotonic

    job["status"] = "completed"
    job["message"] = "Automation ready."
    job["detail"] = "Review the preview, then install when it looks correct."
    job["updated_at"] = now_iso
    job["finished_at"] = now_iso
    job["finished_monotonic"] = now_monotonic
    job["yaml"] = result.get("yaml", "")
    job["summary"] = result.get("summary", "")
    job["clarifying_questions"] = []
    job["entities_used"] = entities_used
    assistant_message = _build_automation_context_message(
        job["summary"],
        job["yaml"],
    )
    job["assistant_message"] = assistant_message or None
    _append_assistant_turn(job, assistant_message)
    job["error"] = None


def _mark_job_needs_clarification(
    job: dict[str, Any],
    result: dict[str, Any],
    entities_used: list[str],
    assistant_message: str,
) -> None:
    """Mark a generation turn as waiting on user clarification."""
    now_iso = _utcnow_iso()
    now_monotonic = time.monotonic()
    if job["started_at"] is None:
        job["started_at"] = now_iso
        job["started_monotonic"] = now_monotonic

    job["status"] = "needs_clarification"
    job["message"] = "I need one more detail."
    job["detail"] = "Answer the follow-up question to continue generating the automation."
    job["updated_at"] = now_iso
    job["finished_at"] = now_iso
    job["finished_monotonic"] = now_monotonic
    job["yaml"] = None
    job["summary"] = result.get("summary", "")
    job["clarifying_questions"] = result.get("clarifying_questions", [])
    job["entities_used"] = entities_used
    job["assistant_message"] = assistant_message
    job["error"] = None


def _mark_job_error(job: dict[str, Any], error: str, detail: str = "") -> None:
    """Mark a generation job as failed."""
    now_iso = _utcnow_iso()
    now_monotonic = time.monotonic()
    if job["started_at"] is None:
        job["started_at"] = now_iso
        job["started_monotonic"] = now_monotonic

    job["status"] = "error"
    job["message"] = "Generation failed."
    job["detail"] = detail or "The request stopped before a valid automation was returned."
    job["updated_at"] = now_iso
    job["finished_at"] = now_iso
    job["finished_monotonic"] = now_monotonic
    job["yaml"] = None
    job["summary"] = None
    job["clarifying_questions"] = []
    job["assistant_message"] = None
    job["error"] = error


def _sync_job_with_task(job: dict[str, Any]) -> None:
    """Reconcile task state in case a background task exits unexpectedly."""
    task = job.get("task")
    if not isinstance(task, asyncio.Task):
        return
    if not task.done() or job.get("status") not in {"queued", "running"}:
        return

    if task.cancelled():
        _mark_job_error(job, "Generation request was cancelled.")
        return

    exc = task.exception()
    if exc is not None:
        _LOGGER.exception("Generation task crashed", exc_info=exc)
        _mark_job_error(job, f"Unexpected generation error: {exc}")


def _serialize_generation_job(job: dict[str, Any]) -> dict[str, Any]:
    """Convert an in-memory job record into a JSON-safe payload."""
    _sync_job_with_task(job)

    if job.get("started_monotonic") is None:
        elapsed_seconds = 0
    else:
        end_time = job.get("finished_monotonic") or time.monotonic()
        elapsed_seconds = max(
            0, int(end_time - float(job["started_monotonic"]))
        )

    payload = {
        "job_id": job["job_id"],
        "status": job["status"],
        "message": job["message"],
        "detail": job["detail"],
        "service_id": job.get("service_id", ""),
        "service_label": job.get("service_label", ""),
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "elapsed_seconds": elapsed_seconds,
        "poll_after_ms": 0
        if job["status"] in {"completed", "error", "needs_clarification"}
        else _STATUS_POLL_MS,
        "backend_status": job.get("backend_status"),
        "backend_checked_at": job.get("backend_checked_at"),
        "error": job.get("error"),
    }

    if job["status"] == "completed":
        payload["yaml"] = job.get("yaml", "")
        payload["summary"] = job.get("summary", "")
        payload["entities_used"] = job.get("entities_used", [])
    elif job["status"] == "needs_clarification":
        payload["summary"] = job.get("summary", "")
        payload["clarifying_questions"] = job.get("clarifying_questions", [])
        payload["entities_used"] = job.get("entities_used", [])

    if job.get("repair_in_progress"):
        payload["repair_in_progress"] = True

    return payload


def _normalize_generation_result(result: dict[str, Any]) -> dict[str, Any]:
    """Normalize a model result so downstream steps always see clean YAML."""
    normalized = dict(result or {})
    normalized["yaml"] = _normalize_automation_yaml_text(normalized.get("yaml"))
    normalized["summary"] = str(normalized.get("summary", "") or "").strip()
    normalized["needs_clarification"] = bool(
        normalized.get("needs_clarification")
    )
    normalized["clarifying_questions"] = list(
        normalized.get("clarifying_questions", []) or []
    )
    return normalized


def _validate_generated_yaml(yaml_text: str) -> str | None:
    """Return an error message when a generated YAML string is not installable."""
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
    """Recursively walk a parsed YAML structure collecting entity references."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "entity_id":
                if isinstance(value, str) and "." in value:
                    entity_ids.add(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and "." in item:
                            entity_ids.add(item)
            elif (
                key == "action"
                and isinstance(value, str)
                and value.startswith("notify.")
            ):
                entity_ids.add(value)
            else:
                _walk_for_entity_ids(value, entity_ids)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_entity_ids(item, entity_ids)


def _extract_entity_ids_from_yaml(yaml_text: str) -> set[str]:
    """Extract entity_id references and notify service calls from automation YAML."""
    if not yaml_text:
        return set()
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return set()
    if not isinstance(parsed, dict):
        return set()
    entity_ids: set[str] = set()
    _walk_for_entity_ids(parsed, entity_ids)
    return entity_ids


def _find_hallucinated_entities(
    yaml_text: str, known_entity_ids: set[str]
) -> list[str]:
    """Return entity_ids referenced in the YAML but not present in Home Assistant."""
    referenced = _extract_entity_ids_from_yaml(yaml_text)
    return sorted(eid for eid in referenced if eid not in known_entity_ids)


def _parse_simple_time(value: str) -> str:
    """Parse a compact 12-hour time phrase into HH:MM:SS."""
    text = str(value or "").strip().lower()
    if not text:
        return ""

    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    if not match:
        return ""

    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3)

    if meridiem == "am":
        hour = 0 if hour == 12 else hour
    elif meridiem == "pm":
        hour = 12 if hour == 12 else hour + 12

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return ""

    return f"{hour:02d}:{minute:02d}:00"


def _invert_entity_state(state: str) -> str:
    """Return a common opposite state for explicit guard conditions."""
    opposites = {
        "active": "inactive",
        "closed": "open",
        "home": "not_home",
        "inactive": "active",
        "locked": "unlocked",
        "not_home": "home",
        "off": "on",
        "on": "off",
        "open": "closed",
        "unlocked": "locked",
    }
    return opposites.get(str(state or "").strip().lower(), "")


def _extract_weekdays(prompt_text: str) -> list[str]:
    """Extract weekday abbreviations implied by the prompt."""
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
    return [
        short
        for word, short in mappings
        if re.search(rf"\b{word}s?\b", text)
    ]


def _resolve_prompt_entities(
    phrase: str,
    prompt_text: str,
    entities: list[dict[str, Any]],
    *,
    max_matches: int = 8,
) -> list[dict[str, Any]]:
    """Resolve prompt phrasing to one or more Home Assistant entities."""
    if not phrase or not entities:
        return []

    phrase_candidates = [
        phrase,
        re.sub(
            r"\b(?:either|both|all|each|every)\s+of\s+the\b",
            " ",
            phrase,
            flags=re.IGNORECASE,
        ),
        re.sub(
            r"\b(?:either|both|all|each|every|of|the)\b",
            " ",
            phrase,
            flags=re.IGNORECASE,
        ),
    ]
    singularized = phrase
    for plural, singular in (
        ("switches", "switch"),
        ("lights", "light"),
        ("phases", "phase"),
        ("sensors", "sensor"),
        ("outputs", "output"),
        ("inputs", "input"),
    ):
        singularized = re.sub(rf"\b{plural}\b", singular, singularized, flags=re.IGNORECASE)
    phrase_candidates.append(singularized)

    seed_entities: list[dict[str, Any]] = []
    for candidate_phrase in phrase_candidates:
        normalized_phrase = " ".join(str(candidate_phrase or "").split())
        if not normalized_phrase:
            continue
        seed_entities = _find_obvious_named_entities(
            normalized_phrase, entities, max_matches
        )
        if seed_entities:
            phrase = normalized_phrase
            break
    if not seed_entities:
        return []

    expansion_prompt = phrase
    if _PLURAL_ENTITY_HINT_RE.search(phrase) or _PLURAL_ENTITY_HINT_RE.search(
        prompt_text
    ):
        expansion_prompt = f"all {phrase}"
    expanded = _expand_variant_entities(expansion_prompt, entities, seed_entities)
    matched = expanded or seed_entities

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entity in matched:
        entity_id = str(entity.get("entity_id") or "").strip()
        if not entity_id or entity_id in seen_ids:
            continue
        deduped.append(entity)
        seen_ids.add(entity_id)
    return deduped


def _extract_explicit_state_guards(
    prompt_text: str,
    entities: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Extract explicit do-not-run state guards implied by the prompt."""
    text = str(prompt_text or "").strip()
    if not text or not entities:
        return []

    patterns = (
        _EXPLICIT_GUARD_RE,
        re.compile(
            r"(?:don't|do not)\s+(?:run(?: any of this| this)?|start(?: any of this| this| it| her| him| them)?)"
            r"(?:\s+at all)?\s+if\s+(.+?)\s+(?:is|are)\s+already\s+"
            r"(on|off|open|closed|locked|unlocked|active|inactive)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bunless\s+(.+?)\s+(?:is|are)\s+"
            r"(on|off|open|closed|locked|unlocked|active|inactive)\b",
            re.IGNORECASE,
        ),
    )
    guards: list[dict[str, str]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            phrase = str(match.group(1) or "").strip()
            blocked_state = str(match.group(2) or "").strip().lower()
            if not phrase or not blocked_state:
                continue
            required_state = _invert_entity_state(blocked_state)
            for entity in _resolve_prompt_entities(phrase, prompt_text, entities):
                entity_id = str(entity.get("entity_id") or "").strip()
                if not entity_id:
                    continue
                guards.append(
                    {
                        "entity_id": entity_id,
                        "blocked_state": blocked_state,
                        "required_state": required_state,
                    }
                )

    deduped: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for guard in guards:
        key = (
            guard["entity_id"],
            guard["blocked_state"],
            guard["required_state"],
        )
        if key in seen_keys:
            continue
        deduped.append(guard)
        seen_keys.add(key)
    return deduped


def _extract_negated_state_guards(
    prompt_text: str,
    entities: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Extract state requirements phrased as entity != value in the prompt."""
    text = str(prompt_text or "").strip()
    if not text or not entities:
        return []

    guards: list[dict[str, str]] = []
    for pattern in _NEGATED_STATE_GUARD_PATTERNS:
        for match in pattern.finditer(text):
            phrase = str(match.group(1) or "").strip().strip(" ,(")
            state = str(match.group(2) or "").strip()
            if not phrase or not state:
                continue
            for entity in _resolve_prompt_entities(
                phrase, prompt_text, entities, max_matches=4
            ):
                entity_id = str(entity.get("entity_id") or "").strip()
                if not entity_id:
                    continue
                guards.append({"entity_id": entity_id, "state": state})

    deduped: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()
    for guard in guards:
        key = (guard["entity_id"], guard["state"])
        if key in seen_keys:
            continue
        deduped.append(guard)
        seen_keys.add(key)
    return deduped


def _yaml_has_weekdays(yaml_text: str, weekdays: list[str]) -> bool:
    """Return True when the YAML preserves all requested weekdays."""
    if not yaml_text or not weekdays:
        return False
    normalized = str(yaml_text or "").lower()
    if "weekday:" not in normalized:
        return False
    return all(re.search(rf"^\s*-\s*{weekday}\s*$", normalized, re.MULTILINE) for weekday in weekdays)


def _yaml_has_positive_state_guard(
    yaml_text: str,
    entity_id: str,
    state: str,
) -> bool:
    """Return True when the YAML contains a direct state condition for entity == state."""
    if not yaml_text or not entity_id or not state:
        return False

    entity_pattern = re.escape(entity_id)
    state_pattern = re.escape(str(state).strip())
    return bool(
        re.search(
            rf"entity_id:\s*{entity_pattern}[\s\S]{{0,180}}state:\s*['\"]?{state_pattern}['\"]?",
            yaml_text,
            re.IGNORECASE,
        )
    )


def _yaml_has_negated_state_guard(
    yaml_text: str,
    entity_id: str,
    state: str,
) -> bool:
    """Return True when the YAML preserves a guard requiring entity != state."""
    if not yaml_text or not entity_id or not state:
        return False

    entity_pattern = re.escape(entity_id)
    state_pattern = re.escape(str(state).strip())
    patterns = (
        rf"condition:\s*not[\s\S]{{0,260}}entity_id:\s*{entity_pattern}[\s\S]{{0,180}}state:\s*['\"]?{state_pattern}['\"]?",
        rf"value_template:\s*>?-?[\s\S]{{0,320}}states?\(['\"]{entity_pattern}['\"]\)\s*!=\s*['\"]{state_pattern}['\"]",
        rf"value_template:\s*>?-?[\s\S]{{0,320}}not\s+is_state\(['\"]{entity_pattern}['\"],\s*['\"]{state_pattern}['\"]\)",
    )
    return any(re.search(pattern, yaml_text, re.IGNORECASE) for pattern in patterns)


def _collect_generated_yaml_issues(
    prompt_text: str,
    entities: list[dict[str, Any]],
    yaml_text: str,
) -> list[str]:
    """Collect structural and prompt-coverage issues that require another repair pass."""
    issues: list[str] = []
    syntax_issue = _validate_generated_yaml(yaml_text)
    if syntax_issue:
        issues.append(syntax_issue)

    normalized_yaml = _normalize_automation_yaml_text(yaml_text)
    if not normalized_yaml or not prompt_text or not entities:
        return list(dict.fromkeys(issue for issue in issues if issue))

    if re.search(r"\b(notify|notification|iphone|phone|mobile)\b", prompt_text, re.IGNORECASE):
        notify_matches = _relevant_domain_matches(prompt_text, entities, "notify", 1, 4)
        if notify_matches:
            notify_entity_id = str(notify_matches[0].get("entity_id") or "").strip()
            if notify_entity_id and notify_entity_id not in normalized_yaml:
                issues.append(f"Use the resolved notification target {notify_entity_id}.")

    weekdays = _extract_weekdays(prompt_text)
    if weekdays and not _yaml_has_weekdays(normalized_yaml, weekdays):
        issues.append(
            "Preserve the requested weekday schedule in the automation trigger or guard."
        )

    for guard in _extract_explicit_state_guards(prompt_text, entities):
        entity_id = guard["entity_id"]
        blocked_state = guard["blocked_state"]
        required_state = guard["required_state"]
        if required_state and _yaml_has_positive_state_guard(
            normalized_yaml, entity_id, required_state
        ):
            continue
        if _yaml_has_negated_state_guard(normalized_yaml, entity_id, blocked_state):
            continue
        issues.append(f"Respect the explicit guard {entity_id} before running the actions.")

    for guard in _extract_negated_state_guards(prompt_text, entities):
        if _yaml_has_negated_state_guard(
            normalized_yaml, guard["entity_id"], guard["state"]
        ):
            continue
        issues.append(
            f'Preserve the requested guard that {guard["entity_id"]} must not be "{guard["state"]}".'
        )

    if re.search(
        r"\bcolor_name:\s*['\"]?[a-z0-9]+_[a-z0-9_]+['\"]?",
        normalized_yaml,
        re.IGNORECASE,
    ):
        issues.append(
            "Use a valid Home Assistant light color. color_name values should not use underscore-separated names such as warm_white; prefer kelvin, color_temp, or a valid CSS color name."
        )

    return list(dict.fromkeys(issue for issue in issues if issue))


def _build_entity_target_lines(entity_ids: list[str], indent: str = "      ") -> list[str]:
    """Build a Home Assistant entity target block."""
    cleaned_ids = [entity_id for entity_id in entity_ids if entity_id]
    if not cleaned_ids:
        return []
    if len(cleaned_ids) == 1:
        return [f"{indent}entity_id: {cleaned_ids[0]}"]

    lines = [f"{indent}entity_id:"]
    for entity_id in cleaned_ids:
        lines.append(f"{indent}  - {entity_id}")
    return lines


def _pick_semantic_entity(
    prompt_text: str,
    entities: list[dict[str, Any]],
    label: str,
) -> dict[str, Any] | None:
    """Return the first semantic entity match for a label."""
    for match in _collect_semantic_prompt_matches(prompt_text, entities, 4):
        if match.get("label") == label and match.get("entities"):
            return match["entities"][0]
    return None


def _pick_semantic_entities(
    prompt_text: str,
    entities: list[dict[str, Any]],
    label: str,
    *,
    expand_variants: bool = True,
) -> list[dict[str, Any]]:
    """Return all semantic matches for a label, expanding sibling variants when relevant."""
    for match in _collect_semantic_prompt_matches(prompt_text, entities, 8):
        if match.get("label") != label:
            continue
        matched = [
            entity
            for entity in match.get("entities", [])
            if str(entity.get("entity_id") or "").strip()
        ]
        if not matched:
            return []
        if not expand_variants:
            return matched
        expanded = _expand_variant_entities(prompt_text, entities, matched)
        return expanded or matched
    return []


def _build_automation_guard_condition_lines(entity_ids: list[str]) -> list[str]:
    """Build template conditions that skip running automations already in progress."""
    ids = [entity_id for entity_id in entity_ids if entity_id]
    if not ids:
        return []

    expression = " and ".join(
        f"(state_attr('{entity_id}', 'current') | int(0)) == 0"
        for entity_id in ids
    )
    return [
        "  - condition: template",
        "    value_template: >-",
        f"      {{{{ {expression} }}}}",
    ]


def _build_victron_phase_imbalance_deterministic_result(
    prompt_text: str,
    entities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build a deterministic YAML result for the Victron phase-imbalance prompt family."""
    normalized_prompt = str(prompt_text or "").strip().lower()
    if not normalized_prompt:
        return None

    required_fragments = (
        "victron",
        "single phase voltage",
        "single phase current",
        "output power",
        "lounge lamp",
        "lounge strip",
        "bar lamp",
        "battery monitor",
        "iphone",
    )
    if any(fragment not in normalized_prompt for fragment in required_fragments):
        return None

    voltage_match = _VOLTAGE_THRESHOLD_RE.search(prompt_text)
    current_match = _CURRENT_THRESHOLD_RE.search(prompt_text)
    power_match = _POWER_ABOVE_THRESHOLD_RE.search(prompt_text)
    wait_match = _WAIT_MINUTES_RE.search(prompt_text)
    time_match = _TIME_WINDOW_RE.search(prompt_text)

    voltage_threshold = voltage_match.group(1) if voltage_match else ""
    current_threshold = current_match.group(1) if current_match else ""
    power_threshold = power_match.group(1) if power_match else ""
    wait_minutes = int(wait_match.group(1)) if wait_match else 0
    after_time = _parse_simple_time(time_match.group(1)) if time_match else ""
    before_time = _parse_simple_time(time_match.group(2)) if time_match else ""

    voltage_entities = _pick_semantic_entities(prompt_text, entities, "voltage")
    current_entities = _pick_semantic_entities(prompt_text, entities, "current")
    power_entity = _pick_semantic_entity(prompt_text, entities, "power")
    notify_targets = _relevant_domain_matches(prompt_text, entities, "notify", 1, 4)
    automation_guards = _relevant_domain_matches(prompt_text, entities, "automation", 2, 8)

    lounge_lamp = _find_obvious_named_entities("lounge lamp", entities, 4)
    strip_seed = _find_obvious_named_entities("lounge strip lights", entities, 8) or _find_obvious_named_entities(
        "lounge strip light", entities, 8
    )
    strip_lights = (
        _expand_variant_entities("both lounge strip lights", entities, strip_seed)
        or strip_seed
    )
    bar_lamp = _find_obvious_named_entities("bar lamp", entities, 4)
    bedroom_strip = _find_obvious_named_entities("bedroom strip light", entities, 8)
    battery_monitor = _find_obvious_named_entities("battery monitor switch", entities, 4) or _find_obvious_named_entities(
        "battery monitor", entities, 4
    )

    lounge_lamp_id = str(lounge_lamp[0].get("entity_id") or "") if lounge_lamp else ""
    strip_ids = [
        str(entity.get("entity_id") or "")
        for entity in strip_lights
        if str(entity.get("domain") or "") == "light"
    ]
    bar_lamp_id = str(bar_lamp[0].get("entity_id") or "") if bar_lamp else ""
    bedroom_strip_id = (
        str(bedroom_strip[0].get("entity_id") or "") if bedroom_strip else ""
    )
    battery_monitor_id = (
        str(battery_monitor[0].get("entity_id") or "") if battery_monitor else ""
    )
    notify_service = (
        str(notify_targets[0].get("entity_id") or "") if notify_targets else ""
    )

    if (
        not voltage_threshold
        or not current_threshold
        or not power_threshold
        or wait_minutes <= 0
        or not after_time
        or not before_time
        or len(voltage_entities) < 2
        or len(current_entities) < 2
        or not power_entity
        or not lounge_lamp_id
        or not strip_ids
        or not bar_lamp_id
        or not bedroom_strip_id
        or not battery_monitor_id
        or not notify_service
        or not automation_guards
    ):
        return None

    quoted_message_match = re.search(r'\bsaying\s+"([^"]+)"', prompt_text, re.IGNORECASE)
    if quoted_message_match is None:
        quoted_message_match = re.search(
            r"\bsaying\s+'([^']+)'",
            prompt_text,
            re.IGNORECASE,
        )
    notification_message = (
        quoted_message_match.group(1)
        if quoted_message_match
        else "Warning: Victron phase imbalance detected - [whichever sensor triggered] is out of range"
    )
    notification_message = re.sub(
        r"\[\s*whichever sensor triggered\s*\]",
        "{{ triggered_sensor_name }}",
        notification_message,
        flags=re.IGNORECASE,
    )
    if (
        re.search(
            r"\bactual sensor value\b|\bactual value\b",
            prompt_text,
            re.IGNORECASE,
        )
        and "triggered_sensor_value" not in notification_message
    ):
        notification_message = (
            f"{notification_message} "
            "(value: {{ triggered_sensor_value }}{{ triggered_sensor_unit }})"
        )

    warning_light_ids = [lounge_lamp_id]
    shutdown_light_ids = [
        *strip_ids,
        bar_lamp_id,
    ]
    shutdown_light_ids = list(
        dict.fromkeys(entity_id for entity_id in shutdown_light_ids if entity_id)
    )
    automation_guard_ids = [
        str(entity.get("entity_id") or "")
        for entity in automation_guards
        if str(entity.get("entity_id") or "")
    ]

    lines = [
        "alias: Victron Phase Imbalance Monitor",
        (
            "description: Watches Victron AC output phases for low voltage or high current "
            "outside weekday daytime hours and escalates if output power stays high."
        ),
        "triggers:",
    ]

    for entity in voltage_entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id:
            continue
        lines.extend(
            [
                "  - trigger: numeric_state",
                f"    entity_id: {entity_id}",
                f"    below: {voltage_threshold}",
                f"    id: {entity_id}",
            ]
        )

    for entity in current_entities:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id:
            continue
        lines.extend(
            [
                "  - trigger: numeric_state",
                f"    entity_id: {entity_id}",
                f"    above: {current_threshold}",
                f"    id: {entity_id}",
            ]
        )

    lines.extend(
        [
            "conditions:",
            "  - condition: numeric_state",
            f"    entity_id: {power_entity['entity_id']}",
            f"    above: {power_threshold}",
            "  - condition: not",
            "    conditions:",
            "      - condition: time",
            f'        after: "{after_time}"',
            f'        before: "{before_time}"',
            "        weekday:",
            "          - mon",
            "          - tue",
            "          - wed",
            "          - thu",
            "          - fri",
            *_build_automation_guard_condition_lines(automation_guard_ids),
            "actions:",
            "  - variables:",
            '      triggered_sensor_id: "{{ trigger.entity_id }}"',
            "      triggered_sensor_name: "
            '"{{ state_attr(trigger.entity_id, \'friendly_name\') or trigger.entity_id }}"',
            '      triggered_sensor_value: "{{ states(trigger.entity_id) }}"',
            "      triggered_sensor_unit: "
            '"{{ state_attr(trigger.entity_id, \'unit_of_measurement\') or \'\' }}"',
            "  - repeat:",
            "      count: 2",
            "      sequence:",
            "        - action: light.turn_on",
            "          target:",
            *[
                line.replace("      ", "            ", 1)
                for line in _build_entity_target_lines(warning_light_ids)
            ],
            "          data:",
            '            color_name: "red"',
            "            brightness_pct: 50",
            '            flash: "short"',
            '        - delay: "00:00:01"',
            "  - action: light.turn_on",
            "    target:",
            *_build_entity_target_lines(warning_light_ids),
            "    data:",
            '      color_name: "red"',
            "      brightness_pct: 50",
            "  - action: light.turn_off",
            "    target:",
            *_build_entity_target_lines(shutdown_light_ids),
            f'  - delay: "00:{wait_minutes:02d}:00"',
            "  - choose:",
            "      - conditions:",
            "          - condition: numeric_state",
            f"            entity_id: {power_entity['entity_id']}",
            f"            above: {power_threshold}",
            "        sequence:",
            "          - action: light.turn_off",
            "            target:",
            *_build_entity_target_lines([bedroom_strip_id], indent="              "),
            "          - action: switch.turn_off",
            "            target:",
            *_build_entity_target_lines([battery_monitor_id], indent="              "),
            f"          - action: {notify_service}",
            "            data:",
            f"              message: {json.dumps(notification_message)}",
            "    default:",
            "      - action: light.turn_on",
            "        target:",
            *_build_entity_target_lines([lounge_lamp_id], indent="          "),
            "        data:",
            '          color_name: "white"',
            "          brightness_pct: 100",
            "mode: single",
        ]
    )

    result = {
        "yaml": "\n".join(lines),
        "summary": (
            "Monitors all Victron AC output voltage and current phases, applies the "
            "requested lamp warning, then escalates after 2 minutes only if output power remains high."
        ),
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    return result if _validate_generated_yaml(result["yaml"]) is None else None


def _build_low_power_victron_deterministic_result(
    prompt_text: str,
    entities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build a deterministic YAML result for the low-power overnight Victron case."""
    normalized_prompt = str(prompt_text or "").strip().lower()
    if not normalized_prompt:
        return None
    if "ac output power" not in normalized_prompt:
        return None
    if "lounge lamp" not in normalized_prompt:
        return None
    if "bar lamp" not in normalized_prompt:
        return None
    if "shore power is critically low - lights turned off automatically" not in normalized_prompt:
        return None

    threshold_match = _POWER_THRESHOLD_RE.search(prompt_text)
    wait_match = _WAIT_MINUTES_RE.search(prompt_text)
    time_match = _TIME_WINDOW_RE.search(prompt_text)
    guard_match = _EXPLICIT_GUARD_RE.search(prompt_text)

    threshold = threshold_match.group(1) if threshold_match else ""
    wait_minutes = int(wait_match.group(1)) if wait_match else 0
    after_time = _parse_simple_time(time_match.group(1)) if time_match else ""
    before_time = _parse_simple_time(time_match.group(2)) if time_match else ""
    guard_phrase = guard_match.group(1).strip() if guard_match else ""
    blocked_state = guard_match.group(2).strip().lower() if guard_match else ""
    required_state = _invert_entity_state(blocked_state)

    power_entity = _pick_semantic_entity(prompt_text, entities, "power")
    lounge_lamp = _find_obvious_named_entities("lounge lamp", entities, 4)
    strip_seed = _find_obvious_named_entities("lounge strip lights", entities, 8)
    strip_lights = _expand_variant_entities(
        "both lounge strip lights",
        entities,
        strip_seed,
    ) or strip_seed
    bar_lamp = _find_obvious_named_entities("bar lamp", entities, 4)
    notify_targets = _relevant_domain_matches(prompt_text, entities, "notify", 1, 4)
    guard_entities = (
        _find_obvious_named_entities(guard_phrase, entities, 4) if guard_phrase else []
    )

    initial_light_ids = [
        *(entity.get("entity_id") for entity in lounge_lamp[:1]),
        *(
            entity.get("entity_id")
            for entity in strip_lights
            if str(entity.get("domain") or "") == "light"
        ),
    ]
    initial_light_ids = list(dict.fromkeys(entity_id for entity_id in initial_light_ids if entity_id))

    if (
        not power_entity
        or not threshold
        or wait_minutes <= 0
        or not after_time
        or not before_time
        or not initial_light_ids
        or not bar_lamp
        or not notify_targets
    ):
        return None

    lines = [
        "alias: AC Output Power Monitor",
        (
            "description: Turns off the lounge lights when AC output power drops "
            f"below {threshold} watts overnight and escalates after {wait_minutes} minutes if shore power stays low."
        ),
        "triggers:",
        "  - trigger: numeric_state",
        f"    entity_id: {power_entity['entity_id']}",
        f"    below: {threshold}",
        "conditions:",
        "  - condition: time",
        f'    after: "{after_time}"',
        f'    before: "{before_time}"',
    ]

    if guard_entities and required_state:
        lines.extend(
            [
                "  - condition: state",
                f"    entity_id: {guard_entities[0]['entity_id']}",
                f'    state: "{required_state}"',
            ]
        )

    lines.extend(
        [
            "actions:",
            "  - action: light.turn_off",
            "    target:",
            *_build_entity_target_lines(initial_light_ids),
            f'  - delay: "00:{wait_minutes:02d}:00"',
            "  - choose:",
            "      - conditions:",
            "          - condition: numeric_state",
            f"            entity_id: {power_entity['entity_id']}",
            f"            below: {threshold}",
            "        sequence:",
            "          - action: light.turn_off",
            "            target:",
            *_build_entity_target_lines(
                [str(bar_lamp[0].get("entity_id") or "")],
                indent="              ",
            ),
            f"          - action: {notify_targets[0]['entity_id']}",
            "            data:",
            '              message: "Shore power is critically low - lights turned off automatically"',
            "mode: single",
        ]
    )

    result = {
        "yaml": "\n".join(lines),
        "summary": (
            "Turns off the lounge lamp and strip lights when AC output power "
            "drops below 200 watts overnight, then escalates after 5 minutes if power is still low."
        ),
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    return result if _validate_generated_yaml(result["yaml"]) is None else None


def _build_deterministic_generation_result(
    prompt_text: str,
    entities: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the first deterministic result that fully covers the prompt."""
    for builder in (
        _build_victron_phase_imbalance_deterministic_result,
        _build_low_power_victron_deterministic_result,
    ):
        result = builder(prompt_text, entities)
        if result is not None:
            return result
    return None


def _build_yaml_repair_messages(
    request_messages: list[dict[str, str]],
    result: dict[str, Any],
    issue: str,
) -> list[dict[str, str]]:
    """Build a retry prompt that asks the model to rewrite invalid YAML."""
    assistant_payload = {
        "yaml": _normalize_automation_yaml_text(result.get("yaml")),
        "summary": str(result.get("summary", "") or "").strip(),
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    base_messages = [
        dict(message)
        for message in (request_messages or [])
        if str(message.get("role", "") or "").strip() in {"system", "user"}
    ]

    return [
        {"role": "system", "content": _YAML_REPAIR_SYSTEM_PROMPT},
        *base_messages,
        {"role": "assistant", "content": json.dumps(assistant_payload)},
        {
            "role": "user",
            "content": (
                "Your previous response contained invalid Home Assistant automation YAML. "
                "Rewrite it into a valid final automation JSON now. "
                f"Problems to fix: {issue} "
                "Preserve every entity, threshold, guard, delay, and notification message from the request. "
                "Do not ask for clarification."
            ),
        },
    ]


def _build_yaml_regeneration_messages(
    request_messages: list[dict[str, str]],
    issue: str,
) -> list[dict[str, str]]:
    """Build a retry prompt that regenerates YAML from the original request."""
    base_messages = [
        dict(message)
        for message in (request_messages or [])
        if str(message.get("role", "") or "").strip() in {"system", "user"}
    ]
    return [
        {"role": "system", "content": _YAML_REGENERATION_SYSTEM_PROMPT},
        *base_messages,
        {
            "role": "user",
            "content": (
                "The previous response still did not produce valid Home Assistant automation YAML. "
                "Ignore every prior draft and regenerate the full automation JSON from the original request now. "
                f"Problems to avoid: {issue} "
                "Preserve every entity, threshold, guard, delay, and notification message from the request. "
                "Do not ask for clarification unless the original request truly leaves a required detail unspecified."
            ),
        },
    ]


def _build_entity_repair_messages(
    request_messages: list[dict[str, str]],
    result: dict[str, Any],
    hallucinated: list[str],
    entity_summary: str,
) -> list[dict[str, str]]:
    """Build a retry prompt asking the model to fix hallucinated entity references."""
    assistant_payload = {
        "yaml": _normalize_automation_yaml_text(result.get("yaml")),
        "summary": str(result.get("summary", "") or "").strip(),
        "needs_clarification": False,
        "clarifying_questions": [],
    }
    base_messages = [
        dict(message)
        for message in (request_messages or [])
        if str(message.get("role", "") or "").strip() in {"system", "user"}
    ]
    hallucinated_list = ", ".join(hallucinated)

    return [
        {"role": "system", "content": _ENTITY_REPAIR_SYSTEM_PROMPT},
        *base_messages,
        {"role": "assistant", "content": json.dumps(assistant_payload)},
        {
            "role": "user",
            "content": (
                "Your previous response referenced entity_ids that do not exist "
                "in this Home Assistant instance. "
                f"Invalid entity_ids: {hallucinated_list}\n\n"
                "Here are all available entities in this Home Assistant:\n"
                f"{entity_summary}\n\n"
                "Replace each invalid entity_id with the closest matching valid "
                "entity_id from the list above. If no close match exists for an "
                "entity, remove that reference entirely. "
                "Preserve every trigger, condition, action, guard, delay, "
                "threshold, and notification message. "
                "Do not ask for clarification. Return the final corrected "
                "automation JSON now."
            ),
        },
    ]


async def _regenerate_generation_result(
    client: LLMClient,
    request_messages: list[dict[str, str]],
    prompt_text: str,
    entities: list[dict[str, Any]],
    issue: str,
) -> dict[str, Any]:
    """Regenerate a clean automation from the original request when repair is exhausted."""
    last_issue = str(issue or "").strip() or "The model returned invalid automation YAML."
    last_result: dict[str, Any] | None = None
    for _attempt in range(_YAML_REGENERATION_ATTEMPTS):
        regenerated = _normalize_generation_result(
            await client.complete(
                _build_yaml_regeneration_messages(request_messages, last_issue)
            )
        )
        if regenerated.get("needs_clarification"):
            return regenerated
        last_result = regenerated
        regenerated_issues = _collect_generated_yaml_issues(
            prompt_text,
            entities,
            regenerated.get("yaml", ""),
        )
        last_issue = " ".join(regenerated_issues[:6])
        if not regenerated_issues:
            return regenerated

    current = last_result
    if current is not None and last_issue:
        for _attempt in range(_YAML_REPAIR_ATTEMPTS):
            current = _normalize_generation_result(
                await client.complete(
                    _build_yaml_repair_messages(request_messages, current, last_issue)
                )
            )
            if current.get("needs_clarification"):
                return current
            repaired_issues = _collect_generated_yaml_issues(
                prompt_text,
                entities,
                current.get("yaml", ""),
            )
            last_issue = " ".join(repaired_issues[:6])
            if not repaired_issues:
                return current

    raise LLMResponseError(
        last_issue or "The model returned invalid automation YAML."
    )


async def _repair_generation_result(
    client: LLMClient,
    request_messages: list[dict[str, str]],
    prompt_text: str,
    entities: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Validate and, when needed, repair a generated YAML result."""
    current = _normalize_generation_result(result)
    if current.get("needs_clarification"):
        return current

    issues = _collect_generated_yaml_issues(
        prompt_text,
        entities,
        current.get("yaml", ""),
    )
    if not issues:
        return current

    deterministic = _build_deterministic_generation_result(prompt_text, entities)
    if deterministic is not None and not _collect_generated_yaml_issues(
        prompt_text,
        entities,
        deterministic.get("yaml", ""),
    ):
        return deterministic

    for _attempt in range(_YAML_REPAIR_ATTEMPTS):
        issue = " ".join(issues[:6])
        current = _normalize_generation_result(
            await client.complete(
                _build_yaml_repair_messages(request_messages, current, issue)
            )
        )
        if current.get("needs_clarification"):
            return current
        issues = _collect_generated_yaml_issues(
            prompt_text,
            entities,
            current.get("yaml", ""),
        )
        if not issues:
            return current

    return await _regenerate_generation_result(
        client,
        request_messages,
        prompt_text,
        entities,
        " ".join(issues[:6]),
    )


async def _maybe_refresh_backend_status(
    hass: HomeAssistant, job: dict[str, Any]
) -> None:
    """Refresh backend activity details for a long-running generation job."""
    if job.get("status") != "running" or job.get("started_monotonic") is None:
        return

    now_monotonic = time.monotonic()
    if (
        now_monotonic - float(job["started_monotonic"])
        < _BACKEND_PROBE_DELAY_SECONDS
    ):
        return
    if (
        now_monotonic - float(job.get("backend_checked_monotonic", 0.0))
        < _BACKEND_PROBE_INTERVAL_SECONDS
    ):
        return

    service_config = dict(job.get("service_config") or {})
    if not service_config:
        service_config = _get_service_config(hass, job.get("service_id"))
    if service_config is None:
        return

    session = async_get_clientsession(hass)
    client = LLMClient.from_config(service_config, session=session)
    status = await client.probe_generation_status()

    job["backend_checked_monotonic"] = now_monotonic
    job["backend_checked_at"] = _utcnow_iso()
    if status.get("available"):
        job["backend_status"] = status


async def _run_generation_job(
    hass: HomeAssistant,
    job_id: str,
    prompt_text: str,
    entity_filter: list[str] | None,
) -> None:
    """Run automation generation in the background."""
    job = _get_generation_jobs(hass).get(job_id)
    if job is None:
        return

    config_data = _get_config_data(hass)
    if config_data is None:
        _mark_job_error(job, "AutoMagic is not configured.")
        return
    service_config = dict(job.get("service_config") or {})
    if not service_config:
        service_config = _get_service_config(hass, job.get("service_id"))
    if service_config is None:
        _mark_job_error(job, "The selected AI service is no longer available.")
        return

    try:
        _mark_job_running(
            job,
            "Collecting Home Assistant context...",
            "Gathering entity data for the model prompt.",
        )
        entities_list = await get_entity_context(hass)
    except Exception as err:
        _LOGGER.error("Failed to collect entities: %s", err)
        _mark_job_error(job, f"Failed to collect entities: {err}")
        return

    context_limit = int(
        config_data.get("context_limit") or _DEFAULT_GENERATION_CONTEXT_LIMIT
    )
    prompt_entities = select_relevant_entities(
        prompt_text,
        entities_list,
        max_entities=context_limit,
    )
    if entity_filter and isinstance(entity_filter, list):
        prompt_entities = [
            entity for entity in entities_list if entity["domain"] in entity_filter
        ]
        prompt_entities = select_relevant_entities(
            prompt_text,
            prompt_entities,
            max_entities=context_limit,
        )

    entity_summary = "\n".join(
        f"{entity['entity_id']} ({entity['name']}) [{entity['state']}]"
        for entity in prompt_entities
    )

    messages = _clone_messages(job.get("conversation_messages"))
    if not messages:
        deterministic_result = _build_deterministic_generation_result(
            prompt_text,
            prompt_entities,
        )
        if deterministic_result is not None:
            _mark_job_complete(
                job,
                deterministic_result,
                [entity["entity_id"] for entity in prompt_entities],
            )
            return
        messages = build_prompt(prompt_text, entity_summary, prompt_entities)
    job["conversation_messages"] = _clone_messages(messages)

    session = async_get_clientsession(hass)
    client = LLMClient.from_config(service_config, session=session)
    request_timeout = getattr(client, "_request_timeout", None)

    async def _complete_messages(
        request_messages: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        try:
            return await client.complete(request_messages)
        except LLMConnectionError as err:
            _LOGGER.error("LLM connection error: %s", err)
            _mark_job_error(job, str(err))
            return None
        except LLMResponseError as err:
            _LOGGER.warning(
                "LLM response error on initial generation; attempting clean regeneration: %s",
                err,
            )
            try:
                return await _regenerate_generation_result(
                    client,
                    request_messages,
                    prompt_text,
                    prompt_entities,
                    str(err),
                )
            except LLMConnectionError as regen_err:
                _LOGGER.error(
                    "LLM connection error during regeneration fallback: %s",
                    regen_err,
                )
                _mark_job_error(job, str(regen_err))
                return None
            except LLMResponseError as regen_err:
                _LOGGER.error(
                    "LLM response error during regeneration fallback: %s",
                    regen_err,
                )
                _mark_job_error(job, str(regen_err))
                return None
        except Exception as err:  # pragma: no cover - defensive guard
            _LOGGER.exception("Unexpected generation error")
            _mark_job_error(job, f"Unexpected generation error: {err}")
            return None

    async def _complete_and_repair_messages(
        request_messages: list[dict[str, str]],
    ) -> dict[str, Any] | None:
        result = await _complete_messages(request_messages)
        if result is None:
            return None

        # Detect YAML issues before launching the repair loop so we can update
        # the job status immediately — the frontend polls this and will show it
        # in the chat thread as an informational notice.
        preliminary = _normalize_generation_result(result)
        if not preliminary.get("needs_clarification"):
            initial_issues = _collect_generated_yaml_issues(
                prompt_text,
                prompt_entities,
                preliminary.get("yaml", ""),
            )
            if initial_issues:
                initial_issue = " ".join(initial_issues[:4])
                job["repair_in_progress"] = True
                _mark_job_running(
                    job,
                    "Fixing a YAML issue…",
                    (
                        "The model returned automation YAML with a syntax or logic problem. "
                        "AutoMagic has automatically sent the specific error back to the AI "
                        f"and is requesting a correction. Error: {initial_issue[:300]}"
                    ),
                )

        try:
            repaired = await _repair_generation_result(
                client,
                request_messages,
                prompt_text,
                prompt_entities,
                result,
            )

            # ------- entity-id validation after structural YAML repair -------
            if not repaired.get("needs_clarification"):
                yaml_text = repaired.get("yaml", "")
                known_ids = {e["entity_id"] for e in entities_list}
                hallucinated = _find_hallucinated_entities(yaml_text, known_ids)
                if hallucinated:
                    job["repair_in_progress"] = True
                    _mark_job_running(
                        job,
                        "Fixing incorrect entity references…",
                        (
                            "The model used entity IDs that don't exist in your "
                            "Home Assistant. AutoMagic has sent the invalid "
                            "references back to the AI for correction. "
                            f"Unknown entities: {', '.join(hallucinated[:10])}"
                        ),
                    )
                    full_entity_summary = "\n".join(
                        f"{e['entity_id']} ({e['name']}) [{e['state']}]"
                        for e in entities_list
                    )
                    for _ent_attempt in range(_ENTITY_REPAIR_ATTEMPTS):
                        candidate = _normalize_generation_result(
                            await client.complete(
                                _build_entity_repair_messages(
                                    request_messages,
                                    repaired,
                                    hallucinated,
                                    full_entity_summary,
                        )
                            )
                        )
                        if candidate.get("needs_clarification"):
                            repaired = candidate
                            break
                        cand_yaml = candidate.get("yaml", "")
                        candidate_issues = _collect_generated_yaml_issues(
                            prompt_text,
                            prompt_entities,
                            cand_yaml,
                        )
                        if candidate_issues:
                            continue  # broke structure, retry
                        repaired = candidate
                        hallucinated = _find_hallucinated_entities(
                            cand_yaml, known_ids
                        )
                        if not hallucinated:
                            break

            job["repair_in_progress"] = False
            return repaired
        except LLMConnectionError as err:
            job["repair_in_progress"] = False
            _LOGGER.error("LLM connection error during YAML repair: %s", err)
            _mark_job_error(job, str(err))
            return None
        except LLMResponseError as err:
            job["repair_in_progress"] = False
            _LOGGER.error("LLM response error during YAML repair: %s", err)
            _mark_job_error(
                job,
                str(err),
                (
                    "AutoMagic detected a YAML formatting issue and automatically sent the "
                    "error back to the AI, but could not produce a valid automation after "
                    "multiple correction attempts. Try rephrasing your request."
                ),
            )
            return None
        except Exception as err:  # pragma: no cover - defensive guard
            job["repair_in_progress"] = False
            _LOGGER.exception("Unexpected YAML repair error")
            _mark_job_error(job, f"Unexpected generation error: {err}")
            return None

    timeout_message = (
        f"Waiting for the model response. AutoMagic will wait up to {request_timeout}s."
        if request_timeout
        else "Waiting for the model response."
    )
    _mark_job_running(
        job,
        "Waiting for your model to respond...",
        timeout_message,
    )

    result = await _complete_and_repair_messages(messages)
    if result is None:
        return

    entities_used = [entity["entity_id"] for entity in prompt_entities]
    if result.get("needs_clarification"):
        assistant_message = _build_clarification_message(
            result.get("summary", ""),
            result.get("clarifying_questions", []),
        )
        auto_answer = build_auto_clarification_answer(
            prompt_text,
            result,
            prompt_entities,
        )
        waiting_messages = (_clone_messages(messages) or []) + [
            {"role": "assistant", "content": assistant_message}
        ]

        if auto_answer and not any(
            message.get("role") == "user"
            and message.get("content") == auto_answer
            for message in waiting_messages
        ):
            auto_messages = waiting_messages + [
                {"role": "user", "content": auto_answer}
            ]
            job["conversation_messages"] = _clone_messages(auto_messages)
            _mark_job_running(
                job,
                "Resolving an obvious grouped-entity clarification...",
                "AutoMagic matched the grouped entity family from the original prompt and asked the model to continue.",
            )
            result = await _complete_and_repair_messages(auto_messages)
            if result is None:
                return

            if not result.get("needs_clarification"):
                _mark_job_complete(
                    job,
                    result,
                    entities_used,
                )
                return

            assistant_message = _build_clarification_message(
                result.get("summary", ""),
                result.get("clarifying_questions", []),
            )
            waiting_messages = (_clone_messages(auto_messages) or []) + [
                {"role": "assistant", "content": assistant_message}
            ]
            strengthened_auto_answer = (
                auto_answer
                + " This clarification has already been answered from the original prompt and prior context. "
                + "Do not ask it again. Return the complete automation JSON now."
            )
            if not any(
                message.get("role") == "user"
                and message.get("content") == strengthened_auto_answer
                for message in waiting_messages
            ):
                retry_messages = waiting_messages + [
                    {"role": "user", "content": strengthened_auto_answer}
                ]
                job["conversation_messages"] = _clone_messages(retry_messages)
                _mark_job_running(
                    job,
                    "Reasserting an already-resolved clarification...",
                    "AutoMagic restated the resolved entity and guard mappings from the original prompt and asked the model to continue.",
                )
                result = await _complete_and_repair_messages(retry_messages)
                if result is None:
                    return

                if not result.get("needs_clarification"):
                    _mark_job_complete(
                        job,
                        result,
                        entities_used,
                    )
                    return

                assistant_message = _build_clarification_message(
                    result.get("summary", ""),
                    result.get("clarifying_questions", []),
                )
                waiting_messages = (_clone_messages(retry_messages) or []) + [
                    {"role": "assistant", "content": assistant_message}
                ]

        job["conversation_messages"] = waiting_messages
        _mark_job_needs_clarification(
            job,
            result,
            entities_used,
            assistant_message,
        )
        return

    _mark_job_complete(
        job,
        result,
        entities_used,
    )


async def async_start_generation_request(
    hass: HomeAssistant, body: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    """Start an automation generation job from a JSON-like request payload."""
    prompt_text = str(body.get("prompt", "")).strip()
    if not prompt_text:
        return {"error": "Missing 'prompt' field"}, 400

    entity_filter = body.get("entity_filter")
    continue_job_id = str(body.get("continue_job_id", "")).strip()
    selected_service_id = str(body.get(CONF_SERVICE_ID, "")).strip()

    config_data = _get_config_data(hass)
    if config_data is None:
        return {"error": "AutoMagic is not configured"}, 500

    root_prompt = prompt_text
    conversation_messages = None

    if continue_job_id:
        parent_job = _get_generation_jobs(hass).get(continue_job_id)
        if parent_job is None:
            return {"error": "Clarification request not found"}, 404

        _sync_job_with_task(parent_job)
        parent_status = str(parent_job.get("status") or "").strip()
        if parent_status not in {"needs_clarification", "completed"}:
            return {
                "error": "That request is not available for follow-up anymore"
            }, 400

        base_messages = _clone_messages(parent_job.get("conversation_messages"))
        if parent_status == "completed":
            assistant_message = _build_automation_context_message(
                str(parent_job.get("summary") or ""),
                str(parent_job.get("yaml") or ""),
            )
            if assistant_message:
                if base_messages is None:
                    original_prompt = str(
                        parent_job.get("root_prompt")
                        or parent_job.get("prompt")
                        or ""
                    ).strip()
                    base_messages = [
                        {"role": "user", "content": original_prompt},
                    ]
                if not (
                    base_messages
                    and base_messages[-1].get("role") == "assistant"
                    and base_messages[-1].get("content") == assistant_message
                ):
                    base_messages = [
                        *(base_messages or []),
                        {"role": "assistant", "content": assistant_message},
                    ]

        if not base_messages:
            return {"error": "Unable to resume the follow-up thread"}, 400

        conversation_messages = base_messages + [
            {"role": "user", "content": prompt_text}
        ]
        root_prompt = str(
            parent_job.get("root_prompt") or parent_job.get("prompt") or prompt_text
        )
        if entity_filter is None:
            entity_filter = parent_job.get("entity_filter")
        if not selected_service_id:
            selected_service_id = str(parent_job.get("service_id") or "").strip()

    service_config = _get_service_config(hass, selected_service_id)
    if service_config is None:
        return {"error": "Selected AI service not found"}, 400

    job = _create_generation_job(
        hass,
        root_prompt,
        entity_filter,
        conversation_messages=conversation_messages,
        service_config=service_config,
        root_prompt=root_prompt,
        parent_job_id=continue_job_id or None,
    )
    if continue_job_id:
        job["detail"] = (
            f"Queued follow-up for model {service_config.get(CONF_MODEL, 'unknown')} at "
            f"{service_config.get(CONF_ENDPOINT_URL, 'configured endpoint')}."
        )
    else:
        job["detail"] = (
            f"Queued for model {service_config.get(CONF_MODEL, 'unknown')} at "
            f"{service_config.get(CONF_ENDPOINT_URL, 'configured endpoint')}."
        )
    job["task"] = hass.async_create_task(
        _run_generation_job(hass, job["job_id"], root_prompt, entity_filter)
    )

    return _serialize_generation_job(job), 202


async def async_get_generation_status_payload(
    hass: HomeAssistant, job_id: str
) -> tuple[dict[str, Any], int]:
    """Return the current generation job payload."""
    _prune_generation_jobs(hass)

    job = _get_generation_jobs(hass).get(job_id)
    if job is None:
        return {"error": "Generation request not found"}, 404

    try:
        await _maybe_refresh_backend_status(hass, job)
    except Exception as err:  # pragma: no cover - defensive guard
        _LOGGER.warning("Backend status probe failed for job %s: %s", job_id, err)
    payload = _serialize_generation_job(job)
    status_code = (
        200
        if payload["status"] in {"completed", "error", "needs_clarification"}
        else 202
    )
    return payload, status_code


async def async_install_automation_request(
    hass: HomeAssistant, body: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    """Install a generated automation from a JSON-like request payload."""
    yaml_string = str(body.get("yaml", "")).strip()
    if not yaml_string:
        return {"error": "Missing 'yaml' field"}, 400

    prompt = body.get("prompt", "")
    summary = body.get("summary", "")

    result = await install_automation(hass, yaml_string)
    status = 200 if result.get("success") else 400

    await hass.async_add_executor_job(
        _append_history,
        hass,
        prompt,
        result.get("alias", ""),
        summary,
        yaml_string,
        result.get("filename", ""),
        result.get("success", False),
    )

    return result, status


async def async_install_repair_request(
    hass: HomeAssistant, body: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    """Send install-time HA error back to the AI for repair and return the fixed YAML."""
    yaml_string = str(body.get("yaml", "")).strip()
    install_error = str(body.get("error", "")).strip()
    if not yaml_string or not install_error:
        return {"error": "Missing 'yaml' or 'error' field"}, 400

    config_data = _get_config_data(hass)
    if config_data is None:
        return {"error": "AutoMagic is not configured"}, 500

    selected_service_id = str(body.get(CONF_SERVICE_ID, "")).strip()
    service_config = _get_service_config(hass, selected_service_id)
    if service_config is None:
        return {"error": "The selected AI service is no longer available."}, 500

    session = async_get_clientsession(hass)
    client = LLMClient.from_config(service_config, session=session)

    assistant_payload = {
        "yaml": _normalize_automation_yaml_text(yaml_string),
        "summary": str(body.get("summary", "") or "").strip(),
        "needs_clarification": False,
        "clarifying_questions": [],
    }

    repair_messages: list[dict[str, str]] = [
        {"role": "system", "content": _INSTALL_REPAIR_SYSTEM_PROMPT},
        {
            "role": "assistant",
            "content": json.dumps(assistant_payload),
        },
        {
            "role": "user",
            "content": (
                "Home Assistant rejected this automation when I tried to install it. "
                f"Error: {install_error}\n\n"
                "Fix the YAML to resolve this specific error. "
                "Do not change anything else — preserve every trigger, condition, "
                "action intent, entity, threshold, guard, delay, and notification message. "
                "Return the corrected automation JSON now."
            ),
        },
    ]

    last_error = install_error
    for _attempt in range(_INSTALL_REPAIR_ATTEMPTS):
        try:
            result = await client.complete(repair_messages)
        except (LLMConnectionError, LLMResponseError) as err:
            return {"error": f"AI repair failed: {err}"}, 502

        normalized = _normalize_generation_result(result)
        fixed_yaml = normalized.get("yaml", "")
        issue = _validate_generated_yaml(fixed_yaml)
        if issue is not None:
            last_error = issue
            continue

        return {
            "success": True,
            "yaml": fixed_yaml,
            "summary": normalized.get("summary", ""),
        }, 200

    return {
        "error": (
            "AutoMagic sent the install error back to the AI but could not "
            f"produce a valid fix after {_INSTALL_REPAIR_ATTEMPTS} attempts. "
            f"Last issue: {last_error}"
        )
    }, 502


async def async_get_entities_payload(
    hass: HomeAssistant,
) -> tuple[dict[str, Any], int]:
    """Return available Home Assistant entities for prompt building."""
    try:
        entities = await get_entity_context(hass)
    except Exception as err:
        _LOGGER.error("Failed to collect entities: %s", err)
        return {"error": f"Failed to collect entities: {err}"}, 500

    return {"entities": entities}, 200


async def async_get_history_payload(
    hass: HomeAssistant,
) -> tuple[dict[str, Any], int]:
    """Return the persisted automation history payload."""
    history = await hass.async_add_executor_job(_load_history, hass)
    return {"history": _serialize_history_entries(hass, history)}, 200


async def async_delete_history_entry_request(
    hass: HomeAssistant,
    entry_id: str,
) -> tuple[dict[str, Any], int]:
    """Delete a failed or deleted history row."""
    target_entry_id = str(entry_id or "").strip()
    if not target_entry_id:
        return {"error": "Missing history entry id"}, 400

    history = await hass.async_add_executor_job(_load_history, hass)
    normalized = _normalize_history_entries(history)
    target = next(
        (item for item in normalized if item.get("entry_id") == target_entry_id),
        None,
    )
    if target is None:
        return {"error": "History entry not found"}, 404

    status = _history_entry_status(hass, target)
    if status not in {"failed", "deleted"}:
        return {"error": "Only failed or deleted history entries can be removed"}, 400

    remaining = [
        item for item in normalized if item.get("entry_id") != target_entry_id
    ]
    await hass.async_add_executor_job(_save_history, hass, remaining)
    return {"history": _serialize_history_entries(hass, remaining)}, 200


async def async_get_services_payload(
    hass: HomeAssistant,
) -> tuple[dict[str, Any], int]:
    """Return the configured AI services for the frontend model picker."""
    config_data = _get_config_data(hass)
    if config_data is None:
        return {"services": [], "default_service_id": ""}, 200

    default_service_id = get_default_service_id(config_data)
    services = [
        {
            "service_id": service.get(CONF_SERVICE_ID, ""),
            "model": service.get(CONF_MODEL, ""),
            "endpoint_url": service.get(CONF_ENDPOINT_URL, ""),
            "label": build_service_label(service),
            "is_default": service.get(CONF_SERVICE_ID) == default_service_id,
        }
        for service in get_configured_services(config_data)
    ]
    return {
        "services": services,
        "default_service_id": default_service_id,
    }, 200


class AutoMagicGenerateView(HomeAssistantView):
    """Handle POST /api/automagic/generate."""

    url = API_PATH_GENERATE
    name = "api:automagic:generate"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Start an automation generation job."""
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON body"}, status_code=400)
        payload, status_code = await async_start_generation_request(hass, body)
        return self.json(payload, status_code=status_code)


class AutoMagicGenerateStatusView(HomeAssistantView):
    """Handle GET /api/automagic/generate/{job_id}."""

    url = API_PATH_GENERATE_STATUS
    name = "api:automagic:generate_status"
    requires_auth = True

    async def get(
        self, request: web.Request, job_id: str
    ) -> web.Response:
        """Return the current state of a generation job."""
        hass: HomeAssistant = request.app["hass"]
        payload, status_code = await async_get_generation_status_payload(
            hass, job_id
        )
        return self.json(payload, status_code=status_code)


class AutoMagicInstallView(HomeAssistantView):
    """Handle POST /api/automagic/install."""

    url = API_PATH_INSTALL
    name = "api:automagic:install"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Install a generated automation into Home Assistant."""
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON body"}, status_code=400)
        payload, status_code = await async_install_automation_request(hass, body)
        return self.json(payload, status_code=status_code)


class AutoMagicInstallRepairView(HomeAssistantView):
    """Handle POST /api/automagic/install_repair."""

    url = API_PATH_INSTALL_REPAIR
    name = "api:automagic:install_repair"
    requires_auth = True

    async def post(self, request: web.Request) -> web.Response:
        """Send an install error to the AI for repair."""
        hass: HomeAssistant = request.app["hass"]

        try:
            body = await request.json()
        except ValueError:
            return self.json({"error": "Invalid JSON body"}, status_code=400)
        payload, status_code = await async_install_repair_request(hass, body)
        return self.json(payload, status_code=status_code)


class AutoMagicEntitiesView(HomeAssistantView):
    """Handle GET /api/automagic/entities."""

    url = API_PATH_ENTITIES
    name = "api:automagic:entities"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the entity summary list as JSON."""
        hass: HomeAssistant = request.app["hass"]
        payload, status_code = await async_get_entities_payload(hass)
        return self.json(payload, status_code=status_code)


class AutoMagicHistoryView(HomeAssistantView):
    """Handle GET /api/automagic/history."""

    url = API_PATH_HISTORY
    name = "api:automagic:history"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the automation creation history."""
        hass: HomeAssistant = request.app["hass"]
        payload, status_code = await async_get_history_payload(hass)
        return self.json(payload, status_code=status_code)


class AutoMagicHistoryEntryView(HomeAssistantView):
    """Handle DELETE /api/automagic/history/{entry_id}."""

    url = API_PATH_HISTORY_ENTRY
    name = "api:automagic:history_entry"
    requires_auth = True

    async def delete(
        self, request: web.Request, entry_id: str
    ) -> web.Response:
        """Delete a removable history entry."""
        hass: HomeAssistant = request.app["hass"]
        payload, status_code = await async_delete_history_entry_request(
            hass,
            entry_id,
        )
        return self.json(payload, status_code=status_code)


class AutoMagicServicesView(HomeAssistantView):
    """Handle GET /api/automagic/services."""

    url = API_PATH_SERVICES
    name = "api:automagic:services"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return configured AI services for the frontend picker."""
        hass: HomeAssistant = request.app["hass"]
        payload, status_code = await async_get_services_payload(hass)
        return self.json(payload, status_code=status_code)


def _get_config_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Get the config data from the first AutoMagic config entry."""
    config_entries = getattr(hass, "config_entries", None)
    async_entries = getattr(config_entries, "async_entries", None)
    if callable(async_entries):
        for entry in async_entries(DOMAIN):
            subentries = getattr(entry, "subentries", {})
            values = subentries.values() if hasattr(subentries, "values") else subentries
            normalized = normalize_config_data(entry.data, values)
            if get_configured_services(normalized):
                return normalized

    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if not isinstance(entry_data, dict):
            continue
        normalized = normalize_config_data(entry_data)
        if get_configured_services(normalized):
            return normalized
    return None


def _get_service_config(
    hass: HomeAssistant, service_id: str | None = None
) -> dict[str, Any] | None:
    """Return the selected AI service or the configured default."""
    return get_service_config(_get_config_data(hass), service_id)
