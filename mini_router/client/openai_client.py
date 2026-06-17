"""OpenAI-compatible API client."""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class RawStreamResponse:
    """Raw upstream streaming response."""

    response: httpx.Response

    @property
    def status_code(self) -> int:
        """Expose upstream status code."""
        return self.response.status_code

    @property
    def headers(self) -> httpx.Headers:
        """Expose upstream response headers."""
        return self.response.headers

    async def aiter_raw(self) -> AsyncGenerator[bytes, None]:
        """Yield raw upstream bytes without SSE parsing."""
        async for chunk in self.response.aiter_raw():
            yield chunk

    async def aread(self) -> bytes:
        """Read the full upstream body."""
        return await self.response.aread()

    async def aread_raw(self) -> bytes:
        """Read the full upstream body without content decoding."""
        return b"".join([part async for part in self.response.aiter_raw()])

    async def aclose(self) -> None:
        """Close the upstream response."""
        await self.response.aclose()


class OpenAIClient:
    """Client for OpenAI-compatible API with dynamic base_url and api_key."""

    def __init__(
        self,
        timeout: float = 60.0,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialize the OpenAI client.

        Args:
            timeout: Request timeout in seconds
            base_url: (Deprecated) Base URL for the API - use per-request parameter instead
            api_key: (Deprecated) API key for authentication - use per-request parameter instead

        Note:
            base_url and api_key are deprecated and will be removed in a future version.
            Pass them dynamically to chat_completion and chat_completion_stream methods.
        """
        self.timeout = timeout
        # Store deprecated parameters for backward compatibility
        self._deprecated_base_url = base_url
        self._deprecated_api_key = api_key
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=timeout,
                write=10.0,
                pool=10.0,
            )
        )

    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        base_url: str | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call chat completion API (non-streaming).

        Args:
            model: Model name
            messages: List of chat messages
            base_url: Base URL for the API (e.g., "http://api.com/v1").
                      If not provided, uses deprecated constructor value.
            api_key: API key for authentication.
                     If not provided, uses deprecated constructor value.
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            API response as dictionary

        Raises:
            ValueError: If base_url is not provided (neither in call nor constructor)
        """
        # Use provided values or fall back to deprecated constructor values
        effective_base_url = base_url or self._deprecated_base_url
        effective_api_key = api_key or self._deprecated_api_key

        if not effective_base_url:
            raise ValueError(
                "base_url is required. Pass it to chat_completion() or provide "
                "it in the constructor (deprecated)."
            )

        headers = {"Content-Type": "application/json"}
        if effective_api_key:
            headers["Authorization"] = f"Bearer {effective_api_key}"

        payload = {
            "model": model,
            "messages": messages,
            **kwargs,
        }

        url = f"{effective_base_url.rstrip('/')}/chat/completions"
        logger.info("api_call_start", url=url, model=model, timeout=self.timeout)

        try:
            response = await self.client.post(
                url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            logger.info("api_call_success", url=url, model=model)
            return result
        except httpx.HTTPStatusError as e:
            logger.error(
                "api_http_error",
                url=url,
                model=model,
                status_code=e.response.status_code,
                response_text=e.response.text[:500] if e.response.text else None,
            )
            raise
        except httpx.TimeoutException as e:
            logger.error(
                "api_timeout_error",
                url=url,
                model=model,
                timeout=self.timeout,
                error_type=type(e).__name__,
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "api_request_error",
                url=url,
                model=model,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    async def chat_completion_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        base_url: str | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream chat completion with parsed SSE chunks.

        Args:
            model: Model name
            messages: List of chat messages
            base_url: Base URL for the API.
                      If not provided, uses deprecated constructor value.
            api_key: API key for authentication.
                     If not provided, uses deprecated constructor value.
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Yields:
            Parsed JSON chunks from the streaming response.

        Raises:
            ValueError: If base_url is not provided (neither in call nor constructor)
        """
        raw_response = await self.open_chat_completion_stream(
            model=model,
            messages=messages,
            base_url=base_url,
            api_key=api_key,
            **kwargs,
        )

        try:
            raw_response.response.raise_for_status()
            async for line in raw_response.response.aiter_lines():
                if not line:
                    continue

                if line.startswith("data: "):
                    data = line[6:]

                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                        yield chunk
                    except json.JSONDecodeError:
                        logger.warning(
                            "stream_json_decode_error",
                            line=line[:100],
                        )
                        continue
        except httpx.HTTPStatusError as e:
            logger.error(
                "stream_http_error",
                url=str(e.request.url) if e.request else None,
                model=model,
                status_code=e.response.status_code,
            )
            raise
        except httpx.TimeoutException:
            logger.error(
                "stream_timeout_error",
                model=model,
                timeout=self.timeout,
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "stream_request_error",
                model=model,
                error=str(e),
            )
            raise
        finally:
            await raw_response.aclose()

    async def open_chat_completion_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        base_url: str | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> RawStreamResponse:
        """Open a raw upstream streaming response without parsing SSE."""
        effective_base_url = base_url or self._deprecated_base_url
        effective_api_key = api_key or self._deprecated_api_key

        if not effective_base_url:
            raise ValueError(
                "base_url is required. Pass it to open_chat_completion_stream() or provide "
                "it in the constructor (deprecated)."
            )

        headers = {"Content-Type": "application/json"}
        if effective_api_key:
            headers["Authorization"] = f"Bearer {effective_api_key}"

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs,
        }

        url = f"{effective_base_url.rstrip('/')}/chat/completions"
        logger.info("stream_api_call_start", url=url, model=model)

        try:
            request = self.client.build_request(
                "POST",
                url,
                headers=headers,
                json=payload,
            )
            response = await self.client.send(request, stream=True)
            return RawStreamResponse(response=response)
        except httpx.TimeoutException:
            logger.error(
                "stream_timeout_error",
                url=url,
                model=model,
                timeout=self.timeout,
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "stream_request_error",
                url=url,
                model=model,
                error=str(e),
            )
            raise

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()
