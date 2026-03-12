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
    CONF_ENDPOINT_URL,
    CONF_MODEL,
    DOMAIN,
)
from .entity_collector import get_entity_context, get_entity_summary_string
from .llm_client import LLMClient, LLMConnectionError, LLMResponseError
from .prompt_builder import build_prompt

_LOGGER = logging.getLogger(__name__)
_HISTORY_FILE = "automagic_history.json"
_GENERATION_JOB_KEY = f"{DOMAIN}_generation_jobs"
_JOB_TTL_SECONDS = 3600
_STATUS_POLL_MS = 2000
_BACKEND_PROBE_DELAY_SECONDS = 15
_BACKEND_PROBE_INTERVAL_SECONDS = 10


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
        if job.get("status") in {"completed", "error"}
        and now - job.get("finished_monotonic", job.get("created_monotonic", now))
        > _JOB_TTL_SECONDS
    ]
    for job_id in stale_ids:
        jobs.pop(job_id, None)


def _create_generation_job(
    hass: HomeAssistant, prompt: str, entity_filter: list[str] | None
) -> dict[str, Any]:
    """Create a new generation job record."""
    _prune_generation_jobs(hass)

    now_iso = _utcnow_iso()
    now_monotonic = time.monotonic()
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
        "entities_used": [],
        "error": None,
        "task": None,
    }

    _get_generation_jobs(hass)[job["job_id"]] = job
    return job


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
    job["entities_used"] = entities_used
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
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "elapsed_seconds": elapsed_seconds,
        "poll_after_ms": 0
        if job["status"] in {"completed", "error"}
        else _STATUS_POLL_MS,
        "backend_status": job.get("backend_status"),
        "backend_checked_at": job.get("backend_checked_at"),
        "error": job.get("error"),
    }

    if job["status"] == "completed":
        payload["yaml"] = job.get("yaml", "")
        payload["summary"] = job.get("summary", "")
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

    config_data = _get_config_data(hass)
    if config_data is None:
        return

    session = async_get_clientsession(hass)
    client = LLMClient.from_config(config_data, session=session)
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

    try:
        _mark_job_running(
            job,
            "Collecting Home Assistant context...",
            "Gathering entity data for the model prompt.",
        )
        entity_summary = await get_entity_summary_string(hass)
        entities_list = await get_entity_context(hass)
    except Exception as err:
        _LOGGER.error("Failed to collect entities: %s", err)
        _mark_job_error(job, f"Failed to collect entities: {err}")
        return

    prompt_entities = entities_list
    if entity_filter and isinstance(entity_filter, list):
        prompt_entities = [
            entity for entity in entities_list if entity["domain"] in entity_filter
        ]
        entity_summary = "\n".join(
            f"{entity['entity_id']} ({entity['name']}) [{entity['state']}]"
            for entity in prompt_entities
        )

    messages = build_prompt(prompt_text, entity_summary)

    session = async_get_clientsession(hass)
    client = LLMClient.from_config(config_data, session=session)
    request_timeout = getattr(client, "_request_timeout", None)
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

    try:
        result = await client.complete(messages)
    except LLMConnectionError as err:
        _LOGGER.error("LLM connection error: %s", err)
        _mark_job_error(job, str(err))
        return
    except LLMResponseError as err:
        _LOGGER.error("LLM response error: %s", err)
        _mark_job_error(job, str(err))
        return
    except Exception as err:  # pragma: no cover - defensive guard
        _LOGGER.exception("Unexpected generation error")
        _mark_job_error(job, f"Unexpected generation error: {err}")
        return

    _mark_job_complete(
        job,
        result,
        [entity["entity_id"] for entity in prompt_entities],
    )


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

        prompt_text = body.get("prompt", "").strip()
        if not prompt_text:
            return self.json({"error": "Missing 'prompt' field"}, status_code=400)

        entity_filter = body.get("entity_filter")

        config_data = _get_config_data(hass)
        if config_data is None:
            return self.json(
                {"error": "AutoMagic is not configured"}, status_code=500
            )

        job = _create_generation_job(hass, prompt_text, entity_filter)
        job["detail"] = (
            f"Queued for model {config_data.get(CONF_MODEL, 'unknown')} at "
            f"{config_data.get(CONF_ENDPOINT_URL, 'configured endpoint')}."
        )
        job["task"] = hass.async_create_task(
            _run_generation_job(hass, job["job_id"], prompt_text, entity_filter)
        )

        return self.json(_serialize_generation_job(job), status_code=202)


class AutoMagicGenerateStatusView(HomeAssistantView):
    """Handle GET /api/automagic/generate/{job_id}."""

    url = API_PATH_GENERATE_STATUS
    name = "api:automagic:generate_status"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the current state of a generation job."""
        hass: HomeAssistant = request.app["hass"]
        _prune_generation_jobs(hass)

        job_id = request.match_info.get("job_id", "")
        job = _get_generation_jobs(hass).get(job_id)
        if job is None:
            return self.json(
                {"error": "Generation request not found"}, status_code=404
            )

        await _maybe_refresh_backend_status(hass, job)
        payload = _serialize_generation_job(job)
        status_code = 200 if payload["status"] in {"completed", "error"} else 202
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

        yaml_string = body.get("yaml", "").strip()
        if not yaml_string:
            return self.json(
                {"error": "Missing 'yaml' field"}, status_code=400
            )

        prompt = body.get("prompt", "")
        summary = body.get("summary", "")

        result = await install_automation(hass, yaml_string)
        status = 200 if result.get("success") else 400

        # Record in history
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

        return self.json(result, status_code=status)


class AutoMagicEntitiesView(HomeAssistantView):
    """Handle GET /api/automagic/entities."""

    url = API_PATH_ENTITIES
    name = "api:automagic:entities"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the entity summary list as JSON."""
        hass: HomeAssistant = request.app["hass"]

        try:
            entities = await get_entity_context(hass)
        except Exception as err:
            _LOGGER.error("Failed to collect entities: %s", err)
            return self.json(
                {"error": f"Failed to collect entities: {err}"}, status_code=500
            )

        return self.json({"entities": entities})


class AutoMagicHistoryView(HomeAssistantView):
    """Handle GET /api/automagic/history."""

    url = API_PATH_HISTORY
    name = "api:automagic:history"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Return the automation creation history."""
        hass: HomeAssistant = request.app["hass"]
        history = await hass.async_add_executor_job(_load_history, hass)
        return self.json({"history": history})


def _get_config_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Get the config data from the first AutoMagic config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_data in domain_data.values():
        if (
            isinstance(entry_data, dict)
            and CONF_ENDPOINT_URL in entry_data
            and CONF_MODEL in entry_data
        ):
            return entry_data
    return None
