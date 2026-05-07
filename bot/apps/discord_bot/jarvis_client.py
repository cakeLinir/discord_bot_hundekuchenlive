# jarvis_client.py - Async HTTP client for the JARVIS backend, used by the Hundekuchen Discord Bot.
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import aiohttp

TRUE_VALUES = {"1", "true", "yes", "y", "on"}


@dataclass(slots=True)
class JarvisClient:
    """Async HTTP client for the JARVIS backend.

    This client runs inside the existing HundekuchenBot process.
    It never uses the Discord bot token. It only uses the internal
    JARVIS_BOT_BRIDGE_TOKEN for JARVIS backend authorization.
    """

    enabled: bool
    base_url: str
    api_token: str
    timeout_seconds: int = 8

    @classmethod
    def from_env(cls) -> "JarvisClient":
        raw_enabled = os.getenv(
            "JARVIS_BRIDGE_ENABLED",
            os.getenv("JARVIS_ENABLED", "false"),
        ).strip().lower()

        raw_timeout = os.getenv(
            "JARVIS_API_TIMEOUT_SECONDS",
            os.getenv("JARVIS_TIMEOUT_SECONDS", "8"),
        ).strip()

        try:
            timeout_seconds = int(raw_timeout)
        except ValueError:
            timeout_seconds = 8

        base_url = os.getenv(
            "JARVIS_BACKEND_URL",
            os.getenv("JARVIS_API_BASE_URL", "http://127.0.0.1:8181"),
        ).strip().rstrip("/")

        api_token = os.getenv(
            "JARVIS_BOT_BRIDGE_TOKEN",
            os.getenv("JARVIS_API_TOKEN", ""),
        ).strip()

        return cls(
            enabled=raw_enabled in TRUE_VALUES,
            base_url=base_url,
            api_token=api_token,
            timeout_seconds=timeout_seconds,
        )

    def _url(self, endpoint: str) -> str:
        return urljoin(self.base_url.rstrip("/") + "/", endpoint.lstrip("/"))

    def _headers(self, *, auth: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json"}

        if auth and self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        return headers

    async def request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> tuple[int, Any]:
        if not self.enabled:
            return 503, {"error": "JARVIS bridge disabled"}

        if auth and not self.api_token:
            return 500, {"error": "JARVIS_BOT_BRIDGE_TOKEN fehlt"}

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        url = self._url(endpoint)

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=self._headers(auth=auth),
            ) as session:
                async with session.request(method, url, json=payload) as response:
                    content_type = response.headers.get("Content-Type", "")

                    if "application/json" in content_type:
                        body = await response.json(content_type=None)
                    else:
                        body = {"raw": await response.text()}

                    return response.status, body

        except asyncio.TimeoutError:
            return 504, {
                "error": "JARVIS backend timeout",
                "url": url,
                "timeoutSeconds": self.timeout_seconds,
            }

        except aiohttp.ClientConnectorError as exc:
            return 503, {
                "error": "JARVIS backend nicht erreichbar",
                "url": url,
                "detail": str(exc),
            }

        except aiohttp.ClientError as exc:
            return 502, {
                "error": "JARVIS backend request failed",
                "url": url,
                "detail": str(exc),
            }

    async def get_json(self, endpoint: str, *, auth: bool = True) -> tuple[int, Any]:
        return await self.request_json("GET", endpoint, auth=auth)

    async def post_json(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        auth: bool = True,
    ) -> tuple[int, Any]:
        return await self.request_json("POST", endpoint, payload, auth=auth)

    async def health(self) -> tuple[int, Any]:
        return await self.get_json("/api/health", auth=False)

    async def agent_status(self) -> tuple[int, Any]:
        return await self.get_json("/api/agent/status")

    async def morning_log(self) -> tuple[int, Any]:
        return await self.get_json("/api/agent/morning-log")

    async def recent_commands(self) -> tuple[int, Any]:
        return await self.get_json("/api/commands/recent")

    async def dev_news(self) -> tuple[int, Any]:
        return await self.get_json("/api/news/dev", auth=False)

    async def create_command(
        self,
        command_type: str,
        requested_by: str,
        *,
        discord_user_id: str | None = None,
        discord_role_ids: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        return await self.post_json(
            "/api/commands",
            {
                "type": command_type,
                "requestedBy": requested_by,
                "discordUserId": discord_user_id,
                "discordRoleIds": discord_role_ids or [],
                "payload": payload or {},
            },
        )