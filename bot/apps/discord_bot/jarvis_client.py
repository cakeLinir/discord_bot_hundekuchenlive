from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import aiohttp


@dataclass(slots=True)
class JarvisClient:
    """HTTP client for the JARVIS backend bridge."""

    enabled: bool
    base_url: str
    api_token: str
    health_endpoint: str = "/health"
    status_endpoint: str = "/modules"
    timeout_seconds: int = 5

    @classmethod
    def from_env(cls) -> "JarvisClient":
        return cls(
            enabled=os.getenv("JARVIS_BRIDGE_ENABLED", "").strip().lower()
            in {"1", "true", "yes", "y", "on"},
            base_url=os.getenv("JARVIS_API_BASE_URL", "http://127.0.0.1:8000").strip(),
            api_token=os.getenv("JARVIS_API_TOKEN", "").strip(),
            health_endpoint=os.getenv("JARVIS_HEALTH_ENDPOINT", "/health").strip() or "/health",
            status_endpoint=os.getenv("JARVIS_STATUS_ENDPOINT", "/modules").strip() or "/modules",
            timeout_seconds=int(os.getenv("JARVIS_API_TIMEOUT_SECONDS", "5")),
        )

    def _url(self, endpoint: str) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", endpoint.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def request_json(
        self,
        method: str,
        endpoint: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        if not self.enabled:
            return 503, {"detail": "JARVIS bridge disabled"}

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)

        async with aiohttp.ClientSession(timeout=timeout, headers=self._headers()) as session:
            async with session.request(method, self._url(endpoint), json=json) as response:
                try:
                    body: Any = await response.json(content_type=None)
                except Exception:
                    body = {"raw": await response.text()}

                return response.status, body

    async def get_json(self, endpoint: str) -> tuple[int, Any]:
        return await self.request_json("GET", endpoint)

    async def post_json(self, endpoint: str, payload: dict[str, Any]) -> tuple[int, Any]:
        return await self.request_json("POST", endpoint, json=payload)

    async def health(self) -> tuple[int, Any]:
        return await self.get_json(self.health_endpoint)

    async def status(self) -> tuple[int, Any]:
        return await self.get_json(self.status_endpoint)

    async def agents(self) -> tuple[int, Any]:
        return await self.get_json("/agents")

    async def enqueue_agent_job(
        self,
        *,
        agent_id: str,
        job_type: str,
        payload: dict[str, Any],
    ) -> tuple[int, Any]:
        return await self.post_json(
            f"/agents/{agent_id}/jobs",
            {
                "job_type": job_type,
                "payload": payload,
            },
        )