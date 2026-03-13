"""Async HTTP client for OpenAI-compatible LLM endpoints."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from .const import (
    CONF_ENDPOINT_URL,
    CONF_MAX_TOKENS,
    CONF_MODEL,
    CONF_REQUEST_TIMEOUT,
    CONF_TEMPERATURE,
    DEFAULT_REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:[a-z0-9_+-]+)?\s*\n?(.*?)\n?\s*```", re.DOTALL | re.IGNORECASE)
_LEADING_LIST_MARKER_RE = re.compile(r"^(?:[-*]\s+|\d+[\).\s]+)")
_QUESTION_STARTERS = (
    "which ",
    "what ",
    "when ",
    "where ",
    "who ",
    "how ",
    "do you ",
    "does ",
    "should ",
    "would ",
    "could ",
    "can you ",
    "is it ",
    "are there ",
)
_FIELD_LINE_RE = re.compile(
    r"^\s*(summary|needs_clarification|clarifying_questions|questions|follow_up_questions)\s*:",
    re.IGNORECASE,
)

STATUS_PROBE_TIMEOUT = 5


class LLMConnectionError(Exception):
    """Raised when the LLM endpoint is unreachable."""


class LLMResponseError(Exception):
    """Raised when the LLM response cannot be parsed."""


def _normalize_text(raw: Any) -> str:
    """Return a stripped string representation for a response field."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip()


def _normalize_questions(raw: Any) -> list[str]:
    """Normalize question fields into a clean list of strings."""
    items: list[str] = []

    if raw is None:
        return items

    if isinstance(raw, str):
        candidates = raw.splitlines()
    elif isinstance(raw, list):
        candidates = raw
    else:
        candidates = [raw]

    for candidate in candidates:
        text = _normalize_text(candidate)
        if not text:
            continue
        text = _LEADING_LIST_MARKER_RE.sub("", text).strip()
        if text:
            items.append(text)

    return items


def _looks_like_question(text: str) -> bool:
    """Heuristic for models that ask a question in summary without schema fields."""
    normalized = _normalize_text(text).lower()
    if not normalized:
        return False
    return normalized.endswith("?") or normalized.startswith(_QUESTION_STARTERS)


def _extract_loose_yaml_response(content: str) -> dict[str, Any] | None:
    """Salvage YAML when the model ignores the requested JSON wrapper."""
    raw_text = _normalize_text(content)
    fence_match = _FENCE_RE.search(raw_text)
    text = _normalize_text(fence_match.group(1) if fence_match else raw_text)
    if not text:
        return None

    lines = text.splitlines()
    first_nonempty_index = next(
        (index for index, line in enumerate(lines) if _normalize_text(line)),
        -1,
    )
    if first_nonempty_index != -1 and re.match(
        r"^\s*yaml\s*$",
        lines[first_nonempty_index],
        re.IGNORECASE,
    ):
        lines = lines[first_nonempty_index + 1 :]
        first_nonempty_index = next(
            (index for index, line in enumerate(lines) if _normalize_text(line)),
            -1,
        )
    if first_nonempty_index != -1 and re.match(
        r"^\s*yaml\s*:?\s*(\|)?\s*$",
        lines[first_nonempty_index],
        re.IGNORECASE,
    ):
        body_lines = lines[first_nonempty_index + 1 :]
        if "|" in lines[first_nonempty_index]:
            indents = [
                len(line) - len(line.lstrip())
                for line in body_lines
                if line.strip()
            ]
            if indents:
                min_indent = min(indents)
                body_lines = [
                    line[min_indent:] if len(line) >= min_indent else ""
                    for line in body_lines
                ]
        lines = body_lines

    summary = ""
    for line in lines:
        if re.match(r"^\s*summary\s*:", line, re.IGNORECASE):
            summary = _normalize_text(re.sub(r"^\s*summary\s*:\s*", "", line, flags=re.IGNORECASE))
            break

    alias_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^\s*(?:-\s*)?alias\s*:", line, re.IGNORECASE)
        ),
        -1,
    )

    if alias_index == -1:
        yaml_label_index = next(
            (index for index, line in enumerate(lines) if re.match(r"^\s*yaml\s*:?\s*$", line, re.IGNORECASE)),
            -1,
        )
        if yaml_label_index != -1:
            alias_index = next(
                (
                    index
                    for index, line in enumerate(lines)
                    if index > yaml_label_index
                    and re.match(r"^\s*(?:-\s*)?alias\s*:", line, re.IGNORECASE)
                ),
                -1,
            )

    if alias_index == -1:
        return None

    yaml_lines = lines[alias_index:]
    trailing_index = next(
        (
            index
            for index, line in enumerate(yaml_lines)
            if index > 0 and _FIELD_LINE_RE.match(line)
        ),
        -1,
    )
    if trailing_index != -1:
        yaml_lines = yaml_lines[:trailing_index]

    yaml_text = "\n".join(yaml_lines).strip()
    if re.match(r"^\s*-\s*alias\s*:", yaml_text, re.IGNORECASE):
        list_lines = yaml_text.splitlines()
        first_line = re.sub(r"^(\s*)-\s+", r"\1", list_lines[0], count=1)
        normalized_lines = [first_line]
        for line in list_lines[1:]:
            if not line.strip():
                normalized_lines.append("")
                continue
            normalized_lines.append(line[2:] if line.startswith("  ") else line)
        candidate = "\n".join(normalized_lines).strip()
        if re.search(r"^alias\s*:", candidate, re.MULTILINE):
            yaml_text = candidate

    if not yaml_text:
        return None
    if not re.search(r"^alias\s*:", yaml_text, re.MULTILINE):
        return None
    if not re.search(r"^(triggers?|trigger|platform)\s*:", yaml_text, re.MULTILINE):
        return None
    if not re.search(r"^(actions?|action|service)\s*:", yaml_text, re.MULTILINE):
        return None

    return {
        "yaml": yaml_text,
        "summary": summary,
        "needs_clarification": False,
        "clarifying_questions": [],
    }


class LLMClient:
    """Client for OpenAI-compatible /v1/chat/completions endpoints."""

    def __init__(
        self,
        endpoint_url: str,
        model: str,
        max_tokens: int = 2048,
        request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
        temperature: float = 0.2,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
        self._request_timeout = request_timeout
        self._temperature = temperature
        self._session = session

    @classmethod
    def from_config(
        cls, config: dict[str, Any], session: aiohttp.ClientSession | None = None
    ) -> LLMClient:
        """Create an LLMClient from a HA config entry data dict."""
        return cls(
            endpoint_url=config[CONF_ENDPOINT_URL],
            model=config[CONF_MODEL],
            max_tokens=config.get(CONF_MAX_TOKENS, 2048),
            request_timeout=config.get(
                CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT
            ),
            temperature=config.get(CONF_TEMPERATURE, 0.2),
            session=session,
        )

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Send messages to the LLM and return parsed JSON content.

        Returns:
            Parsed dict from the LLM's JSON response (expected keys: yaml, summary).

        Raises:
            LLMConnectionError: If the endpoint is unreachable or times out.
            LLMResponseError: If the response cannot be parsed.
        """
        url = f"{self._endpoint_url}/v1/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": False,
        }

        timeout = aiohttp.ClientTimeout(total=self._request_timeout)

        try:
            session = self._session or aiohttp.ClientSession()
            try:
                async with session.post(
                    url, json=payload, timeout=timeout
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        raise LLMResponseError(
                            f"LLM returned HTTP {resp.status} from {url}: {body[:500]}"
                        )
                    data = await resp.json()
            finally:
                if self._session is None:
                    await session.close()

            return self._parse_response(data)

        except TimeoutError:
            raise LLMConnectionError(
                f"LLM request timed out after {self._request_timeout}s to {url}"
            ) from None
        except aiohttp.ClientError as err:
            raise LLMConnectionError(
                f"Cannot connect to LLM endpoint {url}: {err}"
            ) from err

    async def probe_generation_status(self) -> dict[str, Any]:
        """Probe backend status while a long-running request is in flight.

        Currently only Ollama exposes useful active-generation state.
        """
        url = f"{self._endpoint_url}/api/ps"
        timeout = aiohttp.ClientTimeout(total=STATUS_PROBE_TIMEOUT)

        try:
            session = self._session or aiohttp.ClientSession()
            try:
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status != 200:
                        return {
                            "available": False,
                            "backend": "unknown",
                            "message": "",
                        }
                    data = await resp.json()
            finally:
                if self._session is None:
                    await session.close()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return {"available": False, "backend": "unknown", "message": ""}

        models = [
            model.get("name")
            for model in data.get("models", [])
            if isinstance(model, dict) and model.get("name")
        ]

        if not models:
            return {
                "available": True,
                "backend": "ollama",
                "active": False,
                "message": "Ollama is reachable, but it did not report an active model.",
            }

        target = self._model.lower()
        active_model = next(
            (
                model_name
                for model_name in models
                if target == model_name.lower()
                or target.startswith(model_name.lower())
                or model_name.lower().startswith(target)
            ),
            models[0],
        )

        if active_model.lower() == target or active_model.lower().startswith(target):
            message = (
                f"Ollama reports {active_model} is loaded and the request is still running."
            )
        else:
            message = (
                f"Ollama reports an active model ({active_model}) while this request is still open."
            )

        return {
            "available": True,
            "backend": "ollama",
            "active": True,
            "model": active_model,
            "message": message,
        }

    def _parse_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract and parse the JSON content from an OpenAI-format response."""
        try:
            choices = data.get("choices")
            if not choices:
                raise LLMResponseError(f"No choices in LLM response: {data}")

            content = choices[0].get("message", {}).get("content", "")
            if not content:
                raise LLMResponseError("Empty content in LLM response")

            # Strip markdown fences if present
            fence_match = _FENCE_RE.search(content)
            if fence_match:
                content = fence_match.group(1)

            content = content.strip()
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = _extract_loose_yaml_response(content)
                if parsed is None:
                    raise

            if not isinstance(parsed, dict):
                raise LLMResponseError(
                    f"LLM response is not a JSON object: {type(parsed)}"
                )

            yaml_text = _normalize_text(parsed.get("yaml"))
            summary = _normalize_text(parsed.get("summary"))
            needs_clarification = bool(parsed.get("needs_clarification"))
            clarifying_questions = _normalize_questions(
                parsed.get("clarifying_questions")
                or parsed.get("questions")
                or parsed.get("follow_up_questions")
            )

            if not yaml_text:
                if clarifying_questions:
                    needs_clarification = True
                elif needs_clarification and summary:
                    clarifying_questions = [summary]
                elif summary and _looks_like_question(summary):
                    needs_clarification = True
                    clarifying_questions = [summary]

            if needs_clarification:
                if not summary:
                    summary = (
                        "I need a bit more detail before I can generate the automation."
                    )
                if not clarifying_questions:
                    clarifying_questions = [summary]
                return {
                    "yaml": None,
                    "summary": summary,
                    "needs_clarification": True,
                    "clarifying_questions": clarifying_questions,
                }

            if not yaml_text:
                raise LLMResponseError(
                    "LLM response did not include automation YAML or clarification questions"
                )

            return {
                "yaml": yaml_text,
                "summary": summary,
                "needs_clarification": False,
                "clarifying_questions": [],
            }

        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as err:
            raise LLMResponseError(f"Failed to parse LLM response: {err}") from err


async def fetch_models(
    endpoint_url: str, session: aiohttp.ClientSession | None = None
) -> list[str]:
    """Fetch available models from an LLM endpoint.

    Tries OpenAI format (/v1/models) first, then Ollama format (/api/tags).
    Returns a list of model name strings.
    """
    base = endpoint_url.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=10)
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        # Try OpenAI format first
        try:
            async with session.get(f"{base}/v1/models", timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m["id"] for m in data.get("data", []) if m.get("id")]
                    if models:
                        return sorted(models)
        except (aiohttp.ClientError, TimeoutError, KeyError):
            pass

        # Fall back to Ollama format
        try:
            async with session.get(f"{base}/api/tags", timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [
                        m["name"] for m in data.get("models", []) if m.get("name")
                    ]
                    if models:
                        return sorted(models)
        except (aiohttp.ClientError, TimeoutError, KeyError):
            pass

        return []

    finally:
        if own_session:
            await session.close()
