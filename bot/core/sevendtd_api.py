from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin

import aiohttp


TokenKind = Literal["read", "admin"]


class SevenDTDAPIError(RuntimeError):
    """Fehler für 7DTD-WebAPI-Anfragen."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        path: str | None = None,
        body: Any = None,
    ):
        super().__init__(message)
        self.status = status
        self.path = path
        self.body = body


class SevenDTDCommandBlockedError(SevenDTDAPIError):
    """Wird geworfen, wenn ein geblockter 7DTD-Command ausgeführt werden soll."""


@dataclass(slots=True)
class SevenDTDToken:
    name: str
    secret: str


@dataclass(slots=True)
class SevenDTDAPIConfig:
    base_url: str
    read_token: SevenDTDToken
    admin_token: SevenDTDToken
    token_name_header: str = "X-SDTD-API-TOKENNAME"
    token_secret_header: str = "X-SDTD-API-SECRET"
    command_endpoint: str = "api/command"
    command_body_key: str = "command"


class SevenDTDAPI:
    """
    Sicherer async Client für die 7 Days to Die Web API.

    Eigenschaften:
    - trennt Readonly- und Admin-Token
    - gibt Secrets nie aus
    - nutzt deine bestätigten API-Endpunkte
    - blockiert gefährliche Console-Commands zentral
    """

    # ------------------------------------------------------------------ #
    # Bestätigte Endpunkte aus deinem API-Probe
    # ------------------------------------------------------------------ #

    OPENAPI_CANDIDATES = (
        "api/openapi",
        "api/OpenAPI",
    )

    SERVER_INFO_CANDIDATES = (
        "api/serverinfo",
        "api/ServerInfo",
    )

    SERVER_STATS_CANDIDATES = (
        "api/serverstats",
        "api/ServerStats",
    )

    PLAYER_CANDIDATES = (
        "api/player",
        "api/Player",
    )

    COMMAND_CANDIDATES = (
        "api/command",
        "api/Command",
    )

    # ------------------------------------------------------------------ #
    # Command-Sicherheit
    # ------------------------------------------------------------------ #
    # Diese Commands werden vom Bot-Core grundsätzlich blockiert.
    # Sie sollen nicht über Discord ausgeführt werden.

    BLOCKED_COMMANDS = {
        "accdecay",
        "admin",
        "adminspeed",
        "agemap",
        "ai",
        "aiddebug",
        "audio",
        "automove",
        "ban",  # später nur über dedizierten /7dtd ban Command mit Checks
        "bents",
        "buff",
        "buffplayer",
        "camera",
        "challenges",
        "chunkobserver",
        "chunkreset",
        "commandpermission",
        "config",
        "createwebuser",
        "creativemenu",
        "cvar",
        "damagereset",
        "debuff",
        "debuffplayer",
        "debuggamestats",
        "debugmenu",
        "debugpanels",
        "decomgr",
        "discord",
        "dms",
        "dynamic",
        "dynamicproperties",
        "enablerendering",
        "exception",
        "exportcurrentconfigs",
        "exportprefab",
        "forceeventdate",
        "gamestage",
        "give",
        "givequest",
        "giveself",
        "giveselfxp",
        "givexp",
        "invalidatecaches",
        "jds",
        "junkdrone",
        "kick",  # später nur über dedizierten /7dtd kick Command mit Checks
        "kickall",
        "kill",
        "killall",
        "lgo",
        "lights",
        "loggamestate",
        "loglevel",
        "mapdata",
        "mem",
        "memprofile",
        "mumblepositionalaudio",
        "na",
        "networkclient",
        "networkserver",
        "newweathersurvival",
        "occlusion",
        "openiddebug",
        "overridemaxplayercount",
        "permissionsallowed",
        "pirs",
        "placeblockrotations",
        "placeblockshapes",
        "playerownedentities",
        "playervisitmap",
        "pois",
        "poiwaypoints",
        "pplist",
        "prefab",
        "prefabeditor",
        "prefabupdater",
        "profilenetwork",
        "profiler",
        "profiling",
        "regionreset",
        "reloadentityclasses",
        "removequest",
        "rendermap",
        "repairchunkdensity",
        "resetallstats",
        "screeneffect",
        "sdcs",
        "setgamepref",
        "setgamestat",
        "settargetfps",
        "sette",
        "settime",
        "setwatervalue",
        "show",
        "showalbedo",
        "showchunkdata",
        "showclouds",
        "showhits",
        "shownormals",
        "showspecular",
        "showswings",
        "showtriggers",
        "shutdown",
        "sleep",
        "sleeper",
        "smoothpoi",
        "smoothworldall",
        "spawnairdrop",
        "spawnentity",
        "spawnentityat",
        "spawnscouts",
        "spawnscreen",
        "spawnsupplycrate",
        "spawnwandering",
        "spectator",
        "spectrum",
        "squarespiral",
        "stab",
        "starve",
        "switchview",
        "systeminfo",
        "tcs",
        "teleport",
        "teleportplayer",
        "teleportpoirelative",
        "testcensor",
        "testdismemberment",
        "testloop",
        "testoccreport",
        "thirsty",
        "tls",
        "tppoi",
        "traderarea",
        "transformdebug",
        "trees",
        "twitch",
        "twitchadmin",
        "versionui",
        "visitmap",
        "vpois",
        "weather",
        "weathersurvival",
        "webpermission",
        "webtokens",
        "whitelist",  # später nur über dedizierten /7dtd whitelist Command mit Checks
        "wsmats",
        "xui",
    }

    # Diese Commands dürfen über execute_safe_command laufen.
    # Alles andere wird blockiert.
    SAFE_COMMANDS = {
        "help",
        "version",
        "gettime",
        "shownexthordetime",
        "getgamepref",
        "getgamestat",
        "getlogpath",
        "getoptions",
        "listplayers",
        "listplayerids",
        "listthreads",
        "listitems",
        "listdlc",
        "saveworld",
        "say",
    }

    COMMAND_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")

    def __init__(self, config: SevenDTDAPIConfig):
        self.config = config

    # ------------------------------------------------------------------ #
    # Factory
    # ------------------------------------------------------------------ #

    @classmethod
    def from_env(cls) -> "SevenDTDAPI":
        base_url = os.getenv("SEVENDTD_API_BASE_URL", "").strip()
        if not base_url:
            raise RuntimeError("SEVENDTD_API_BASE_URL fehlt in .env")

        read_name = os.getenv("SEVENDTD_READ_TOKEN_NAME", "").strip()
        read_secret = os.getenv("SEVENDTD_READ_TOKEN_SECRET", "").strip()

        admin_name = os.getenv("SEVENDTD_ADMIN_TOKEN_NAME", "").strip()
        admin_secret = os.getenv("SEVENDTD_ADMIN_TOKEN_SECRET", "").strip()

        if not read_name or not read_secret:
            raise RuntimeError(
                "SEVENDTD_READ_TOKEN_NAME oder SEVENDTD_READ_TOKEN_SECRET fehlt in .env"
            )

        if not admin_name or not admin_secret:
            raise RuntimeError(
                "SEVENDTD_ADMIN_TOKEN_NAME oder SEVENDTD_ADMIN_TOKEN_SECRET fehlt in .env"
            )

        config = SevenDTDAPIConfig(
            base_url=base_url,
            read_token=SevenDTDToken(name=read_name, secret=read_secret),
            admin_token=SevenDTDToken(name=admin_name, secret=admin_secret),
            token_name_header=os.getenv(
                "SEVENDTD_TOKEN_NAME_HEADER",
                "X-SDTD-API-TOKENNAME",
            ).strip(),
            token_secret_header=os.getenv(
                "SEVENDTD_TOKEN_SECRET_HEADER",
                "X-SDTD-API-SECRET",
            ).strip(),
            command_endpoint=os.getenv(
                "SEVENDTD_COMMAND_ENDPOINT",
                "api/command",
            ).strip(),
            command_body_key=os.getenv(
                "SEVENDTD_COMMAND_BODY_KEY",
                "command",
            ).strip(),
        )

        return cls(config)

    # ------------------------------------------------------------------ #
    # HTTP Basis
    # ------------------------------------------------------------------ #

    def _url(self, path: str) -> str:
        base = self.config.base_url.rstrip("/") + "/"
        clean_path = path.lstrip("/")
        return urljoin(base, clean_path)

    def _headers(self, token_kind: TokenKind) -> dict[str, str]:
        token = self.config.read_token if token_kind == "read" else self.config.admin_token

        return {
            self.config.token_name_header: token.name,
            self.config.token_secret_header: token.secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        token_kind: TokenKind = "read",
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout_seconds: int = 10,
        allow_error: bool = False,
    ) -> tuple[int, Any]:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=self._headers(token_kind),
            ) as session:
                async with session.request(
                    method.upper(),
                    self._url(path),
                    json=json_body,
                    params=params,
                    ssl=False,
                ) as response:
                    raw_text = await response.text()

                    try:
                        body: Any = await response.json(content_type=None)
                    except Exception:
                        body = {"raw": raw_text}

                    if not allow_error and not (200 <= response.status < 300):
                        raise SevenDTDAPIError(
                            f"7DTD API returned HTTP {response.status}",
                            status=response.status,
                            path=path,
                            body=body,
                        )

                    return response.status, body

        except SevenDTDAPIError:
            raise

        except Exception as exc:
            raise SevenDTDAPIError(
                f"7DTD API request failed: {type(exc).__name__}: {exc}",
                path=path,
            ) from exc

    async def first_successful_get(
        self,
        candidates: tuple[str, ...],
        *,
        token_kind: TokenKind = "read",
    ) -> tuple[str, int, Any]:
        errors: list[str] = []

        for path in candidates:
            status, body = await self.request(
                "GET",
                path,
                token_kind=token_kind,
                allow_error=True,
            )

            if 200 <= status < 300:
                return path, status, body

            errors.append(f"{path}=HTTP {status}")

        raise SevenDTDAPIError(
            "Kein passender GET-Endpunkt gefunden: " + ", ".join(errors),
        )

    # ------------------------------------------------------------------ #
    # Probe
    # ------------------------------------------------------------------ #

    async def probe(self) -> list[dict[str, Any]]:
        """
        Testet bekannte GET-Endpunkte mit Readonly-Token.
        Gibt keine Tokenwerte oder Secrets zurück.
        """
        paths: list[str] = []
        paths.extend(("api/openapi.json",))
        paths.extend(self.OPENAPI_CANDIDATES)
        paths.extend(("api/swagger.json",))
        paths.extend(self.SERVER_INFO_CANDIDATES)
        paths.extend(self.SERVER_STATS_CANDIDATES)
        paths.extend(self.PLAYER_CANDIDATES)
        paths.extend(("api/players", "api/Players"))
        paths.extend(self.COMMAND_CANDIDATES)

        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        for path in paths:
            if path in seen:
                continue

            seen.add(path)

            try:
                status, body = await self.request(
                    "GET",
                    path,
                    token_kind="read",
                    allow_error=True,
                    timeout_seconds=6,
                )

                body_type = type(body).__name__
                data_type = (
                    type(body.get("data")).__name__
                    if isinstance(body, dict) and "data" in body
                    else None
                )

                results.append(
                    {
                        "path": path,
                        "status": status,
                        "body_type": body_type,
                        "data_type": data_type,
                    }
                )

            except Exception as exc:
                results.append(
                    {
                        "path": path,
                        "status": "ERR",
                        "body_type": type(exc).__name__,
                        "data_type": None,
                    }
                )

        return results

    # ------------------------------------------------------------------ #
    # API GET Methoden
    # ------------------------------------------------------------------ #

    async def get_openapi(self) -> tuple[str, Any]:
        path, _, body = await self.first_successful_get(
            self.OPENAPI_CANDIDATES,
            token_kind="read",
        )
        return path, body

    async def get_server_info(self) -> tuple[str, Any]:
        path, _, body = await self.first_successful_get(
            self.SERVER_INFO_CANDIDATES,
            token_kind="read",
        )
        return path, body

    async def get_server_stats(self) -> tuple[str, Any]:
        path, _, body = await self.first_successful_get(
            self.SERVER_STATS_CANDIDATES,
            token_kind="read",
        )
        return path, body

    async def get_players(self) -> tuple[str, Any]:
        path, _, body = await self.first_successful_get(
            self.PLAYER_CANDIDATES,
            token_kind="read",
        )
        return path, body

    async def get_full_status(self) -> dict[str, Any]:
        """
        Holt ServerInfo, ServerStats und Player in einem strukturierten Dict.
        Diese Methode ist für /7dtd status ideal.
        """
        info_path, info_body = await self.get_server_info()
        stats_path, stats_body = await self.get_server_stats()
        player_path, player_body = await self.get_players()

        return {
            "server_info": {
                "path": info_path,
                "body": info_body,
            },
            "server_stats": {
                "path": stats_path,
                "body": stats_body,
            },
            "players": {
                "path": player_path,
                "body": player_body,
            },
        }

    # ------------------------------------------------------------------ #
    # Command-Sicherheit
    # ------------------------------------------------------------------ #

    @classmethod
    def command_name(cls, command: str) -> str:
        command = command.strip()
        if not command:
            return ""

        return command.split(maxsplit=1)[0].strip().lower()

    @classmethod
    def validate_command_allowed(cls, command: str) -> None:
        command = command.strip()
        name = cls.command_name(command)

        if not command:
            raise ValueError("Command darf nicht leer sein.")

        if not name:
            raise ValueError("Command-Name konnte nicht gelesen werden.")

        if not cls.COMMAND_NAME_REGEX.fullmatch(name):
            raise SevenDTDCommandBlockedError(
                f"Ungültiger oder nicht erlaubter Command-Name: {name}"
            )

        if name in cls.BLOCKED_COMMANDS:
            raise SevenDTDCommandBlockedError(
                f"Der 7DTD-Command `{name}` ist im Bot-Core blockiert."
            )

        if name not in cls.SAFE_COMMANDS:
            raise SevenDTDCommandBlockedError(
                f"Der 7DTD-Command `{name}` ist nicht in der Allowlist."
            )

    @staticmethod
    def sanitize_chat_message(message: str, *, max_length: int = 200) -> str:
        cleaned = " ".join(message.strip().split())
        cleaned = cleaned.replace('"', "'")

        if not cleaned:
            raise ValueError("Nachricht darf nicht leer sein.")

        if len(cleaned) > max_length:
            raise ValueError(f"Nachricht darf maximal {max_length} Zeichen lang sein.")

        return cleaned

    # ------------------------------------------------------------------ #
    # Command POST
    # ------------------------------------------------------------------ #

    async def execute_safe_command(self, command: str) -> Any:
        """
        Führt nur Commands aus, die:
        - nicht in BLOCKED_COMMANDS sind
        - in SAFE_COMMANDS sind
        """
        command = command.strip()
        self.validate_command_allowed(command)

        endpoint = self.config.command_endpoint or "api/command"
        body_key = self.config.command_body_key or "command"

        status, body = await self.request(
            "POST",
            endpoint,
            token_kind="admin",
            json_body={body_key: command},
            allow_error=True,
            timeout_seconds=15,
        )

        if 200 <= status < 300:
            return body

        # Nur bei eindeutig falschem Pfad Kandidaten testen.
        if status in {404, 405}:
            for candidate in self.COMMAND_CANDIDATES:
                if candidate == endpoint:
                    continue

                candidate_status, candidate_body = await self.request(
                    "POST",
                    candidate,
                    token_kind="admin",
                    json_body={body_key: command},
                    allow_error=True,
                    timeout_seconds=15,
                )

                if 200 <= candidate_status < 300:
                    return candidate_body

        raise SevenDTDAPIError(
            f"Command fehlgeschlagen: HTTP {status}",
            status=status,
            path=endpoint,
            body=body,
        )

    async def execute_command(self, command: str) -> Any:
        """
        Rückwärtskompatibler Alias.
        Nutzt absichtlich dieselbe Sicherheitsprüfung wie execute_safe_command.
        """
        return await self.execute_safe_command(command)

    # ------------------------------------------------------------------ #
    # Komfortmethoden für Bot-Commands
    # ------------------------------------------------------------------ #

    async def save_world(self) -> Any:
        return await self.execute_safe_command("saveworld")

    async def say(self, message: str) -> Any:
        cleaned = self.sanitize_chat_message(message)
        return await self.execute_safe_command(f'say "{cleaned}"')

    async def get_time_command(self) -> Any:
        return await self.execute_safe_command("gettime")

    async def list_players_command(self) -> Any:
        return await self.execute_safe_command("listplayers")

    async def shownexthordetime_command(self) -> Any:
        return await self.execute_safe_command("shownexthordetime")


# ---------------------------------------------------------------------------
# Response Helper
# ---------------------------------------------------------------------------

def extract_data(body: Any) -> Any:
    if isinstance(body, dict) and "data" in body:
        return body["data"]

    return body


def extract_list(body: Any) -> list[Any]:
    data = extract_data(body)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "players",
            "Players",
            "playerList",
            "PlayerList",
            "items",
            "Items",
            "entries",
            "Entries",
            "data",
            "Data",
        ):
            value = data.get(key)
            if isinstance(value, list):
                return value

    if isinstance(body, list):
        return body

    return []


def flatten_key_value_list(body: Any) -> dict[str, Any]:
    """
    api/serverinfo liefert bei dir data=list.
    Häufig ist das eine Liste aus Key/Value-Objekten.
    Diese Funktion macht daraus bestmöglich ein Dict.
    """
    data = extract_data(body)

    if isinstance(data, dict):
        return data

    result: dict[str, Any] = {}

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue

            key = (
                item.get("key")
                or item.get("Key")
                or item.get("name")
                or item.get("Name")
                or item.get("property")
                or item.get("Property")
            )

            value = (
                item.get("value")
                if "value" in item
                else item.get("Value")
                if "Value" in item
                else item.get("currentValue")
                if "currentValue" in item
                else item
            )

            if key:
                result[str(key)] = value

    return result


def extract_player_count(body: Any) -> int | None:
    data = extract_data(body)

    if isinstance(data, dict):
        for key in (
            "playerCount",
            "PlayerCount",
            "players",
            "Players",
            "onlinePlayers",
            "OnlinePlayers",
            "currentPlayers",
            "CurrentPlayers",
        ):
            value = data.get(key)

            if isinstance(value, int):
                return value

            if isinstance(value, list):
                return len(value)

            if isinstance(value, str) and value.isdigit():
                return int(value)

    players = extract_list(body)
    if players:
        return len(players)

    return None