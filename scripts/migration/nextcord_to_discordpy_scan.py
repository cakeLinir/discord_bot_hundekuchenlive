from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BOT_DIR = ROOT / "bot" / "apps" / "discord_bot"


PATTERNS = {
    "import nextcord": "Replace with import discord.",
    "from nextcord": "Replace with from discord or discord.ext.",
    "SlashOption": "Replace with app_commands.describe / typed parameters.",
    "@nextcord.slash_command": "Replace with app_commands.command or app_commands.Group.",
    ".subcommand(": "Review group migration to app_commands.Group.",
    "bot.load_extension(": "discord.py 2.x requires await bot.load_extension(...).",
    "bot.add_cog(": "discord.py 2.x requires await bot.add_cog(...).",
    "def setup(bot": "discord.py 2.x extension setup must be async def setup(bot).",
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    pattern: str
    advice: str


def scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return findings

    for line_number, line in enumerate(lines, start=1):
        for pattern, advice in PATTERNS.items():
            if pattern in line:
                findings.append(
                    Finding(
                        path=path.relative_to(ROOT),
                        line_number=line_number,
                        pattern=pattern,
                        advice=advice,
                    )
                )

    return findings


def main() -> int:
    findings: list[Finding] = []

    for path in sorted(BOT_DIR.rglob("*.py")):
        findings.extend(scan_file(path))

    if not findings:
        print("No nextcord migration findings detected.")
        return 0

    print("Nextcord -> discord.py migration findings:\n")
    for item in findings:
        print(f"- {item.path}:{item.line_number} [{item.pattern}] {item.advice}")

    print(f"\nTotal findings: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
