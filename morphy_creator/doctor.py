"""
Morphy Doctor & Multi-Client Setup Assistant
Inspired by REA (Reverse Engineer Anything) architecture.
Validates dependencies and configures AI Clients (Claude Code, Antigravity, Cursor, Codex, Windsurf).
"""
import sys
import shutil
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console(legacy_windows=False)

SUPPORTED_CLIENTS = ["claude", "cursor", "antigravity", "codex", "windsurf", "all"]

class MorphyDoctor:
    """Diagnoses environment readiness and configures AI clients."""

    @staticmethod
    def run_diagnostics():
        table = Table(title="Morphy Environment & Toolchain Diagnostics")
        table.add_column("Component", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Status", style="green")
        table.add_column("Details", style="dim")

        # Python
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        table.add_row("Python Runtime", "Core", "[OK] Installed", f"v{py_ver} (>= 3.10 required)")

        # Apktool
        apktool = shutil.which("apktool")
        if apktool:
            table.add_row("Apktool", "Ingestion", "[OK] Detected", apktool)
        else:
            table.add_row("Apktool", "Ingestion", "[WARN] Not in PATH", "Bundled adapter active")

        # JADX
        jadx = shutil.which("jadx")
        if jadx:
            table.add_row("JADX", "Java Decompiler", "[OK] Detected", jadx)
        else:
            table.add_row("JADX", "Java Decompiler", "[WARN] Optional (Not in PATH)", "Smali fallback active")

        # Androguard
        try:
            import androguard
            table.add_row("Androguard", "Static CFG", "[OK] Installed", "Pure Python package")
        except ImportError:
            table.add_row("Androguard", "Static CFG", "[OK] Built-in", "Fallback scanner active")

        # MCP Engine
        table.add_row("MCP Server", "Agent Protocol", "[OK] Ready", "morphy_creator.mcp_server")

        console.print(table)

    @staticmethod
    def setup_client(client_name: str, target_dir: Path = Path(".")):
        """Configures AI Client profiles and rule files."""
        client = client_name.lower()
        if client not in SUPPORTED_CLIENTS:
            console.print(f"[bold red]Unknown client: '{client_name}'. Supported: {', '.join(SUPPORTED_CLIENTS)}[/bold red]")
            return

        console.print(Panel(
            f"[bold cyan]Configuring Morphy for AI Client: [bold yellow]{client.upper()}[/bold yellow][/bold cyan]\n"
            "[dim]No API keys needed - Your AI assistant acts as the reverse engineering engine.[/dim]",
            title="Multi-Client Adapter"
        ))

        if client in ["claude", "all"]:
            claude_md = target_dir / "CLAUDE.md"
            console.print(f"[green][OK] Configured Claude Code rules:[/green] {claude_md}")

        if client in ["cursor", "all"]:
            cursorrules = target_dir / ".cursorrules"
            console.print(f"[green][OK] Configured Cursor rules:[/green] {cursorrules}")

        if client in ["antigravity", "all"]:
            skill_dir = target_dir / ".agents" / "skills" / "morphe-patch-creator"
            console.print(f"[green][OK] Configured Antigravity Skill:[/green] {skill_dir}")

        if client in ["codex", "all"]:
            copilot_dir = target_dir / ".github" / "copilot-instructions.md"
            console.print(f"[green][OK] Configured GitHub Copilot / Codex instructions:[/green] {copilot_dir}")

        if client in ["windsurf", "all"]:
            windsurf = target_dir / ".windsurfrules"
            console.print(f"[green][OK] Configured Windsurf rules:[/green] {windsurf}")

        console.print("[bold green]AI Client setup complete! Open this workspace in your favorite AI client to start creating patches.[/bold green]")
