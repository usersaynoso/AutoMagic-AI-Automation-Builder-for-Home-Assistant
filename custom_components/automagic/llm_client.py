"""Async HTTP client for OpenAI-compatible LLM endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import aiohttp

from .const import (
    CONF_API_KEY,
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
_PLAIN_SCALAR_LINE_RE = re.compile(
    r"^(\s*(?:-\s+)?[A-Za-z_][A-Za-z0-9_]*\s*:\s*)(.+?)\s*$"
)
_ALWAYS_QUOTE_SCALAR_KEYS = frozenset({"description", "message"})

STATUS_PROBE_TIMEOUT = 5
COMPLETION_RETRY_ATTEMPTS = 3
_RETRYABLE_HTTP_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_RETRYABLE_PARSE_ERROR_MARKERS = (
    "failed to parse llm response",
    "empty content in llm response",
    "no choices in llm response",
)
_RESPONSE_FORMAT_UNSUPPORTED_RE = re.compile(
    r"(?:response_format|json_object)[\s\S]{0,120}?(?:unsupported|not supported|invalid|unknown)"
    r"|(?:unsupported|not supported|invalid|unknown)[\s\S]{0,120}?(?:response_format|json_object)",
    re.IGNORECASE,
)


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


def _extract_malformed_json_yaml_response(content: str) -> dict[str, Any] | None:
    """Salvage malformed JSON wrappers that embed raw multi-line YAML."""
    text = str(content or "")
    yaml_match = re.search(r'"yaml"\s*:\s*"', text)
    if yaml_match is None:
        return None

    yaml_tail = text[yaml_match.end() :]
    summary_match = re.search(r'([\s\S]*?)"\s*,\s*"summary"\s*:', yaml_tail)
    yaml_only_match = re.search(r'([\s\S]*?)"\s*(?:,|\})', yaml_tail)

    if summary_match is not None:
        yaml_text = summary_match.group(1)
    elif yaml_only_match is not None:
        yaml_text = yaml_only_match.group(1)
    else:
        yaml_text = yaml_tail

    yaml_text = (
        yaml_text.replace("\\r", "")
        .replace("\\n", "\n")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
        .rstrip('"')
        .strip()
    )
    if not yaml_text:
        return None

    summary = ""
    if summary_match is not None:
        summary_tail = yaml_tail[summary_match.end() :]
        if summary_tail.startswith('"'):
            summary_tail = summary_tail[1:]
        summary_end_match = re.search(
            r'([\s\S]*?)"\s*,\s*"'
            r'(?:needs_clarification|clarifying_questions|questions|follow_up_questions)'
            r'"\s*:',
            summary_tail,
        )
        if summary_end_match is not None:
            summary = summary_end_match.group(1)
        else:
            summary = summary_tail.rstrip('"')
        summary = _normalize_text(
            summary.replace("\\r", "")
            .replace("\\n", "\n")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )

    if not re.search(r"^alias\s*:", yaml_text, re.MULTILINE):
        return None

    return {
        "yaml": yaml_text,
        "summary": summary,
        "needs_clarification": False,
        "clarifying_questions": [],
    }


def _sanitize_plain_yaml_scalars(text: str) -> str:
    """Quote plain scalar values that contain ':' so YAML stays parseable."""
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    if not re.search(r"^\s*(?:-\s*)?alias\s*:", normalized, re.MULTILINE):
        return normalized

    # De-indent: when model output is extracted from a ``yaml:`` wrapper,
    # ``.strip()`` (inside ``_normalize_text``) removes the leading
    # whitespace of the very first line but leaves all subsequent lines at
    # their original deeper indentation.  Detect this by comparing the
    # first non-empty line's indent (0 after strip) to the minimum indent
    # of the remaining non-empty lines and shift everything down.
    lines = normalized.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if len(non_empty) > 1:
        first_indent = len(non_empty[0]) - len(non_empty[0].lstrip())
        rest_indents = [
            len(line) - len(line.lstrip()) for line in non_empty[1:]
        ]
        min_rest_indent = min(rest_indents)
        if first_indent == 0 and min_rest_indent > 0:
            lines = [
                line[min_rest_indent:]
                if (
                    line.strip()
                    and len(line) >= min_rest_indent
                    and line[:min_rest_indent].isspace()
                )
                else line
                for line in lines
            ]
    elif non_empty:
        # Single non-empty line or uniform indent — fall back to simple
        # common-indent strip.
        min_indent = min(
            len(line) - len(line.lstrip()) for line in non_empty
        )
        if min_indent > 0:
            lines = [
                line[min_indent:] if len(line) >= min_indent else line
                for line in lines
            ]

    sanitized_lines: list[str] = []
    for line in lines:
        match = _PLAIN_SCALAR_LINE_RE.match(line)
        if match is None:
            sanitized_lines.append(line)
            continue

        prefix, raw_value = match.groups()
        value = raw_value.strip()
        if (
            not value
            or value.startswith(("'", '"', "[", "{", "|", ">", "!", "&", "*"))
            or value.startswith(("{{", "{%"))
        ):
            sanitized_lines.append(line)
            continue

        # Extract the bare key name so we can decide whether to force-quote.
        key_match = re.match(r"\s*(?:-\s+)?([A-Za-z_]\w*)", prefix)
        key_name = key_match.group(1).lower() if key_match else ""

        if ":" in value or key_name in _ALWAYS_QUOTE_SCALAR_KEYS:
            sanitized_lines.append(f"{prefix}{json.dumps(value)}")
        else:
            sanitized_lines.append(line)

    return "\n".join(sanitized_lines)


def _normalize_automation_yaml_text(raw: Any) -> str:
    """Normalize wrapped YAML strings into a direct automation document."""
    text = _normalize_text(raw)
    if not text:
        return ""

    malformed = _extract_malformed_json_yaml_response(text)
    if malformed is not None:
        return _sanitize_plain_yaml_scalars(_normalize_text(malformed.get("yaml")))

    salvaged = _extract_loose_yaml_response(text)
    if salvaged is not None:
        return _sanitize_plain_yaml_scalars(_normalize_text(salvaged.get("yaml")))

    return _sanitize_plain_yaml_scalars(text)


def _is_retryable_http_status(status: int) -> bool:
    """Return True when the provider response is transient enough to retry."""
    return status in _RETRYABLE_HTTP_STATUS_CODES or 500 <= status <= 599


def _should_retry_parse_error(err: Exception) -> bool:
    """Retry transient malformed replies from otherwise successful providers."""
    text = _normalize_text(err).lower()
    return any(marker in text for marker in _RETRYABLE_PARSE_ERROR_MARKERS)


def _response_format_is_unsupported(status: int, body: str) -> bool:
    """Detect providers that reject OpenAI-style json_object output mode."""
    if status not in {400, 404, 415, 422}:
        return False
    return bool(_RESPONSE_FORMAT_UNSUPPORTED_RE.search(_normalize_text(body)))


async def _sleep_before_retry(attempt: int) -> None:
    """Back off slightly between transient provider failures."""
    await asyncio.sleep(min(float(attempt), 2.0))


class LLMClient:
    """Client for OpenAI-compatible /v1/chat/completions endpoints."""

    def __init__(
        self,
        endpoint_url: str,
        model: str,
        max_tokens: int = 2048,
        request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
        temperature: float = 0.2,
        api_key: str = "",
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
        self._request_timeout = request_timeout
        self._temperature = temperature
        self._api_key = api_key.strip()
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
            api_key=config.get(CONF_API_KEY, ""),
            session=session,
        )

    def _request_headers(self) -> dict[str, str]:
        """Return request headers for the configured provider."""
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

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
            "response_format": {"type": "json_object"},
        }
        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        payload_variants = [
            payload,
            {key: value for key, value in payload.items() if key != "response_format"},
        ]

        session = self._session or aiohttp.ClientSession()
        try:
            for variant_index, request_payload in enumerate(payload_variants):
                for attempt in range(1, COMPLETION_RETRY_ATTEMPTS + 1):
                    try:
                        async with session.post(
                            url,
                            json=request_payload,
                            timeout=timeout,
                            headers=self._request_headers(),
                        ) as resp:
                            if resp.status != 200:
                                body = await resp.text()
                                if (
                                    variant_index == 0
                                    and _response_format_is_unsupported(
                                        resp.status, body
                                    )
                                ):
                                    break
                                if (
                                    attempt < COMPLETION_RETRY_ATTEMPTS
                                    and _is_retryable_http_status(resp.status)
                                ):
                                    await _sleep_before_retry(attempt)
                                    continue
                                raise LLMResponseError(
                                    f"LLM returned HTTP {resp.status} from {url}: {body[:500]}"
                                )
                            data = await resp.json()

                        try:
                            return self._parse_response(data)
                        except LLMResponseError as err:
                            if (
                                attempt < COMPLETION_RETRY_ATTEMPTS
                                and _should_retry_parse_error(err)
                            ):
                                await _sleep_before_retry(attempt)
                                continue
                            raise

                    except TimeoutError:
                        if attempt < COMPLETION_RETRY_ATTEMPTS:
                            await _sleep_before_retry(attempt)
                            continue
                        raise LLMConnectionError(
                            f"LLM request timed out after {self._request_timeout}s to {url}"
                        ) from None
                    except aiohttp.ClientError as err:
                        if attempt < COMPLETION_RETRY_ATTEMPTS:
                            await _sleep_before_retry(attempt)
                            continue
                        raise LLMConnectionError(
                            f"Cannot connect to LLM endpoint {url}: {err}"
                        ) from err

            raise LLMResponseError(
                f"LLM endpoint {url} rejected structured JSON responses and did not return a compatible reply."
            )
        finally:
            if self._session is None:
                await session.close()

    async def probe_generation_status(self) -> dict[str, Any]:
        """Probe backend status while a long-running request is in flight.

        Currently only Ollama exposes useful active-generation state.
        """
        url = f"{self._endpoint_url}/api/ps"
        timeout = aiohttp.ClientTimeout(total=STATUS_PROBE_TIMEOUT)

        try:
            session = self._session or aiohttp.ClientSession()
            try:
                async with session.get(
                    url,
                    timeout=timeout,
                    headers=self._request_headers(),
                ) as resp:
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
                parsed = _extract_malformed_json_yaml_response(
                    content
                ) or _extract_loose_yaml_response(content)
                if parsed is None:
                    raise

            if not isinstance(parsed, dict):
                raise LLMResponseError(
                    f"LLM response is not a JSON object: {type(parsed)}"
                )

            yaml_text = _normalize_automation_yaml_text(parsed.get("yaml"))
            intent = parsed.get("intent")
            summary = _normalize_text(parsed.get("summary"))
            needs_clarification = bool(parsed.get("needs_clarification"))
            clarifying_questions = _normalize_questions(
                parsed.get("clarifying_questions")
                or parsed.get("questions")
                or parsed.get("follow_up_questions")
            )

            if not yaml_text and not isinstance(intent, dict):
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
                    "intent": None,
                    "summary": summary,
                    "needs_clarification": True,
                    "clarifying_questions": clarifying_questions,
                }

            if not yaml_text and not isinstance(intent, dict):
                raise LLMResponseError(
                    "LLM response did not include automation YAML, intent JSON, or clarification questions"
                )

            return {
                "yaml": yaml_text,
                "intent": intent if isinstance(intent, dict) else None,
                "summary": summary,
                "needs_clarification": False,
                "clarifying_questions": [],
            }

        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as err:
            raise LLMResponseError(f"Failed to parse LLM response: {err}") from err


async def fetch_models(
    endpoint_url: str,
    session: aiohttp.ClientSession | None = None,
    api_key: str = "",
) -> list[str]:
    """Fetch available models from an LLM endpoint.

    Tries OpenAI format (/v1/models) first, then Ollama format (/api/tags).
    Returns a list of model name strings.
    """
    base = endpoint_url.rstrip("/")
    timeout = aiohttp.ClientTimeout(total=10)
    headers = (
        {"Authorization": f"Bearer {api_key.strip()}"}
        if str(api_key or "").strip()
        else None
    )
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    try:
        # Try OpenAI format first
        try:
            async with session.get(
                f"{base}/v1/models",
                timeout=timeout,
                headers=headers,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m["id"] for m in data.get("data", []) if m.get("id")]
                    if models:
                        return sorted(models)
        except (aiohttp.ClientError, TimeoutError, KeyError):
            pass

        # Fall back to Ollama format
        try:
            async with session.get(
                f"{base}/api/tags",
                timeout=timeout,
                headers=headers,
            ) as resp:
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
