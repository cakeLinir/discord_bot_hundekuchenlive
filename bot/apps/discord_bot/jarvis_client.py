from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import aiohttp


@dataclass(slots=True)
class JarvisClient:
    """Small HTTP client for the future JARVIS bridge.

    The Discord bot must never receive arbitrary executable commands from JARVIS.
    This bridge is intentionally read/status oriented at first. Write actions
    should be added later as explicit, allowlisted capabilities.
    """

    enabled: bool
    base_url: str
    api_token: str
    health_endpoint: str = "/health"
    status_endpoint: str = "/modules"

    @classmethod
    def from_env(cls) -> "JarvisClient":
        return cls(
            enabled=os.getenv("JARVIS_BRIDGE_ENABLED", "").strip().lower()
            in {"1", "true", "yes", "y", "on"},
            base_url=os.getenv("JARVIS_API_BASE_URL", "http://127.0.0.1:8000").strip(),
            api_token=os.getenv("JARVIS_API_TOKEN", "").strip(),
            health_endpoint=os.getenv("JARVIS_HEALTH_ENDPOINT", "/health").strip() or "/health",
            status_endpoint=os.getenv("JARVIS_STATUS_ENDPOINT", "/modules").strip() or "/modules",
        )

    def _url(self, endpoint: str) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", endpoint.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def get_json(self, endpoint: str, *, timeout_seconds: int = 5) -> tuple[int, Any]:
        if not self.enabled:
            return 503, {"detail": "JARVIS bridge disabled"}

        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout, headers=self._headers()) as session:
            async with session.get(self._url(endpoint)) as response:
                try:
                    body: Any = await response.json(content_type=None)
                except Exception:
                    body = {"raw": await response.text()}

                return response.status, body

    async def health(self) -> tuple[int, Any]:
        return await self.get_json(self.health_endpoint)

    async def status(self) -> tuple[int, Any]:
        return await self.get_json(self.status_endpoint)
