from __future__ import annotations

import os

import nextcord
from nextcord import SlashOption
from nextcord.ext import commands

ALLOWED_APPS = {"obs", "discord", "vscode", "whatsapp", "todo"}


class JarvisControl(commands.Cog):
    """Discord bridge to JARVIS backend."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _agent_id(self) -> str:
        return os.getenv("JARVIS_AGENT_ID", "justin-main-pc").strip() or "justin-main-pc"

    def _jarvis(self):
        return getattr(self.bot, "jarvis", None)

    async def _deny_if_disabled(self, interaction: nextcord.Interaction) -> bool:
        jarvis = self._jarvis()

        if jarvis is None or not jarvis.enabled:
            await interaction.response.send_message(
                "JARVIS Bridge ist deaktiviert. Setze `JARVIS_BRIDGE_ENABLED=true`.",
                ephemeral=True,
            )
            return True

        return False

    @nextcord.slash_command(
        name="jarvis",
        description="Steuert JARVIS über den bestehenden HundekuchenBot.",
    )
    async def jarvis_group(self, interaction: nextcord.Interaction) -> None:
        pass

    @jarvis_group.subcommand(
        name="status",
        description="Prüft, ob das JARVIS Backend erreichbar ist.",
    )
    async def jarvis_status(self, interaction: nextcord.Interaction) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        jarvis = self._jarvis()
        status, body = await jarvis.health()

        ok = 200 <= status < 300
        embed = nextcord.Embed(
            title="JARVIS Status",
            color=0x2ECC71 if ok else 0xE74C3C,
        )
        embed.add_field(name="HTTP", value=f"`{status}`", inline=True)
        embed.add_field(name="Backend", value=f"`{jarvis.base_url}`", inline=True)
        embed.add_field(name="Antwort", value=f"```text\n{str(body)[:900]}\n```", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @jarvis_group.subcommand(
        name="agents",
        description="Zeigt registrierte JARVIS Agents.",
    )
    async def jarvis_agents(self, interaction: nextcord.Interaction) -> None:
        if await self._deny_if_disabled(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        jarvis = self._jarvis()
        status, body = await jarvis.agents()

        if not (200 <= status < 300):
            await interaction.followup.send(
                f"Agenten konnten nicht geladen werden: HTTP `{status}`",
                ephemeral=True,
            )
            return

        agents = body.get("agents", []) if isinstance(body, dict) else []

        if not agents:
            await interaction.followup.send("Keine JARVIS Agents registriert.", ephemeral=True)
            return

        lines = []
        for agent in agents[:10]:
            lines.append(
                f"- `{agent.get('agent_id')}` | `{agent.get('status')}` | "
                f"{agent.get('name')} | {', '.join(agent.get('capabilities', []))}"
            )

        await interaction.followup.send(
            "**JARVIS Agents**\n" + "\n".join(lines),
            ephemeral=True,
        )

    @jarvis_group.subcommand(
        name="launch",
        description="Startet eine erlaubte App auf dem JARVIS Desktop-Agent.",
    )
    async def jarvis_launch(
        self,
        interaction: nextcord.Interaction,
        app: str = SlashOption(
            description="App: obs, discord, vscode, whatsapp, todo",
            required=True,
            choices=["obs", "discord", "vscode", "whatsapp", "todo"],
        ),
    ) -> None:
        if await self._deny_if_disabled(interaction):
            return

        app_key = app.lower().strip()

        if app_key not in ALLOWED_APPS:
            await interaction.response.send_message(
                f"Nicht erlaubte App: `{app_key}`",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        jarvis = self._jarvis()
        status, body = await jarvis.enqueue_agent_job(
            agent_id=self._agent_id(),
            job_type="launch_desktop_app",
            payload={"app_key": app_key},
        )

        if 200 <= status < 300:
            job_id = body.get("id", "n/a") if isinstance(body, dict) else "n/a"
            await interaction.followup.send(
                f"JARVIS Job erstellt: `{app_key}` starten. Job-ID: `{job_id}`",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"JARVIS Job konnte nicht erstellt werden: HTTP `{status}`\n```text\n{str(body)[:900]}\n```",
            ephemeral=True,
        )


def setup(bot: commands.Bot) -> None:
    bot.add_cog(JarvisControl(bot))