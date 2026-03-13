"""REST API views for AutoMagic."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .automation_writer import install_automation
from .const import (
    API_PATH_ENTITIES,
    API_PATH_GENERATE,
    API_PATH_GENERATE_STATUS,
    API_PATH_HISTORY,
    API_PATH_INSTALL,
    API_PATH_SERVICES,
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    CONF_SERVICE_ID,
    DOMAIN,
)
from .entity_collector import (
    get_entity_context,
    select_relevant_entities,
)
from .llm_client import LLMClient, LLMConnectionError, LLMResponseError
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
    job["assistant_message"] = None
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

    return payload


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
            _LOGGER.error("LLM response error: %s", err)
            _mark_job_error(job, str(err))
            return None
        except Exception as err:  # pragma: no cover - defensive guard
            _LOGGER.exception("Unexpected generation error")
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

    result = await _complete_messages(messages)
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
            result = await _complete_messages(auto_messages)
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
                result = await _complete_messages(retry_messages)
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
        if parent_job.get("status") != "needs_clarification":
            return {
                "error": "That request is not waiting for clarification anymore"
            }, 400

        base_messages = _clone_messages(parent_job.get("conversation_messages"))
        if not base_messages:
            return {"error": "Unable to resume the clarification thread"}, 400

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
    return {"history": history}, 200


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
