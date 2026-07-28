from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from mia import __version__


class HttpApiError(RuntimeError):
    def __init__(self, status: int | None, message: str, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body[:2000]


@dataclass(slots=True)
class JsonResponse:
    status: int
    data: Any
    headers: dict[str, str]


class AsyncJsonClient:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        query: dict[str, str | int | bool | None] | None = None,
        json_body: Any = None,
    ) -> JsonResponse:
        return await asyncio.to_thread(
            self._request,
            method,
            url,
            headers or {},
            query or {},
            json_body,
        )

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        query: dict[str, str | int | bool | None],
        json_body: Any,
    ) -> JsonResponse:
        filtered = {key: value for key, value in query.items() if value is not None}
        if filtered:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urllib.parse.urlencode(filtered)}"
        request_headers = {
            "Accept": "application/json",
            "User-Agent": f"MIA-OSINT/{__version__} (+https://github.com/)",
            **headers,
        }
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            url,
            data=data,
            headers=request_headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
                payload = json.loads(raw) if raw.strip() else None
                return JsonResponse(
                    status=response.status,
                    data=payload,
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            message = f"API request failed with HTTP {exc.code}"
            try:
                decoded = json.loads(body)
                if isinstance(decoded, dict):
                    message = str(
                        decoded.get("message")
                        or decoded.get("error")
                        or decoded.get("detail")
                        or message
                    )
            except json.JSONDecodeError:
                pass
            raise HttpApiError(exc.code, message, body) from exc
        except urllib.error.URLError as exc:
            raise HttpApiError(None, f"API connection failed: {exc.reason}") from exc
