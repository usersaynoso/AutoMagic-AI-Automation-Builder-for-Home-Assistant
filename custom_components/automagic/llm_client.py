"""Async HTTP client for OpenAI-compatible LLM endpoints."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from .const import CONF_ENDPOINT_URL, CONF_MAX_TOKENS, CONF_MODEL, CONF_TEMPERATURE

_LOGGER = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

REQUEST_TIMEOUT = 60


class LLMConnectionError(Exception):
    """Raised when the LLM endpoint is unreachable."""


class LLMResponseError(Exception):
    """Raised when the LLM response cannot be parsed."""


class LLMClient:
    """Client for OpenAI-compatible /v1/chat/completions endpoints."""

    def __init__(
        self,
        endpoint_url: str,
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url.rstrip("/")
        self._model = model
        self._max_tokens = max_tokens
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

        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        attempts = 2  # retry once on timeout

        for attempt in range(attempts):
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
                if attempt < attempts - 1:
                    _LOGGER.warning("LLM request timed out, retrying (attempt %d)", attempt + 1)
                    continue
                raise LLMConnectionError(
                    f"LLM request timed out after {REQUEST_TIMEOUT}s to {url}"
                ) from None
            except aiohttp.ClientError as err:
                raise LLMConnectionError(
                    f"Cannot connect to LLM endpoint {url}: {err}"
                ) from err

        # Should not reach here, but satisfy type checker
        raise LLMConnectionError(f"LLM request failed after {attempts} attempts to {url}")

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
            parsed = json.loads(content)

            if not isinstance(parsed, dict):
                raise LLMResponseError(
                    f"LLM response is not a JSON object: {type(parsed)}"
                )

            return parsed

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
