"""
Morphy Patches Creator - command line interface.

The default command (``morphy-creator`` with no arguments) is a guided
assistant written for people who do not write code: it asks for an APK, asks
what should change in plain English, shows what it found, and produces a
patch bundle plus a report.

Everything is also scriptable through ``create`` with flags.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from morphy_creator.presets.objectives import OBJECTIVES, Objective, custom_objective, match_text

console = Console(legacy_windows=False, highlight=False)

DEFAULT_OUTPUT = Path("./morphy-output")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _friendly_error(message: str, hint: str = "") -> None:
    console.print(Panel(
        f"[bold red]{escape(message)}[/bold red]"
        + (f"\n\n[dim]{escape(hint)}[/dim]" if hint else ""),
        title="Something went wrong",
        border_style="red",
    ))


def _short_message(message: str, limit: int = 10) -> str:
    """Keeps a panel readable; the full text stays in REPORT.txt."""
    lines = message.splitlines()
    if len(lines) <= limit:
        return message
    return "\n".join(lines[:limit] + ["... (full details in REPORT.txt)"])


def _resolve_apk(raw_path: str) -> Optional[Path]:
    """Accepts drag & drop paths, strips quotes, merges bundles when needed."""
    cleaned = raw_path.strip().strip('"').strip("'")
    path = Path(cleaned).expanduser()
    if not path.exists():
        _friendly_error(
            f"File not found: {cleaned}",
            "Drag the APK file into this window (or copy its full path) and press Enter.",
        )
        return None

    if path.suffix.lower() in (".apkm", ".xapk", ".apks", ".zip"):
        console.print("[cyan]This is a split bundle; extracting the base APK...[/cyan]")
        from morphy_creator.core.split_merger import SplitApkMerger

        base = SplitApkMerger.extract_and_merge(path, DEFAULT_OUTPUT / "merged")
        if not base:
            _friendly_error(
                "No APK found inside this bundle.",
                "If the file came from a bundle installer, try the plain .apk file instead.",
            )
            return None
        console.print(f"[green]Using[/green] {base}")
        return base

    if path.suffix.lower() != ".apk":
        if not Confirm.ask(f"{path.name} is not an .apk file. Try it anyway?", default=False):
            return None
    return path


def _ask_objectives() -> List[Objective]:
    table = Table(title="What should the patch do?", show_header=False, box=None)
    table.add_column(style="cyan", justify="right", width=4)
    table.add_column(style="white")
    for index, objective in enumerate(OBJECTIVES, start=1):
        table.add_row(str(index), f"[bold]{objective.title}[/bold] - {objective.tagline}")
    table.add_row("a", "[bold]Something else[/bold] - describe it in your own words")
    console.print(table)

    while True:
        answer = Prompt.ask(
            "Choose one or more numbers (example: [bold]1,3[/bold]), or [bold]a[/bold]"
        ).strip()
        if not answer:
            continue

        if answer.lower().startswith("a"):
            words = Prompt.ask("In a few words, what should change?").strip()
            matches = match_text(words)
            if matches:
                console.print(
                    "[green]I understood:[/green] " + ", ".join(m.title for m in matches)
                )
                if Confirm.ask("Use these?", default=True):
                    return matches
            keywords = [w for w in words.replace(",", " ").split() if len(w) > 3]
            if not keywords:
                console.print("[yellow]Please use at least one longer word.[/yellow]")
                continue
            console.print(
                f"[cyan]I will search the app for:[/cyan] {', '.join(keywords)}"
            )
            return [custom_objective(keywords)]

        chosen: List[Objective] = []
        for token in answer.replace(" ", ",").split(","):
            if not token:
                continue
            if token.isdigit() and 1 <= int(token) <= len(OBJECTIVES):
                chosen.append(OBJECTIVES[int(token) - 1])
            else:
                matches = match_text(token)
                chosen.extend(matches)

        unique: List[Objective] = []
        seen = set()
        for objective in chosen:
            if objective.id not in seen:
                seen.add(objective.id)
                unique.append(objective)

        if unique:
            return unique
        console.print("[yellow]I did not catch that. Use numbers like 1,3 or 'a'.[/yellow]")


def _parse_objective_flag(value: str) -> List[Objective]:
    chosen: List[Objective] = []
    seen = set()
    for token in value.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        matches: List[Objective] = []
        if token.isdigit() and 1 <= int(token) <= len(OBJECTIVES):
            matches = [OBJECTIVES[int(token) - 1]]
        else:
            matches = [o for o in OBJECTIVES if o.id == token.lower()]
            if not matches:
                matches = match_text(token)
        for objective in matches:
            if objective.id not in seen:
                seen.add(objective.id)
                chosen.append(objective)
    return chosen


def _show_apk_card(info) -> None:
    lines = [
        f"[bold]{escape(info.package or 'unknown package')}[/bold]"
        f"  [dim]version {escape(info.version_name or '?')}[/dim]",
        f"Android {escape(info.min_sdk or '?')}+  |  {info.size_mb} MB"
        f"  |  {len(info.dex_files)} code file(s)"
        f"  |  {sum(len(v) for v in info.native_libs.values())} native librar(y/ies)",
    ]
    if info.packers:
        lines.append(f"[yellow]Protection: {escape(', '.join(info.packers))}[/yellow]")
    console.print(Panel("\n".join(lines), title="The app", border_style="cyan"))


def _confidence_label(score: int) -> str:
    if score >= 8:
        return "[green]high[/green]"
    if score >= 6:
        return "[yellow]medium[/yellow]"
    return "[red]low[/red]"


def _show_findings(report, objectives: Sequence[Objective], details: bool = False) -> None:
    table = Table(title="What I found in the app", show_lines=False)
    table.add_column("Goal", style="cyan")
    table.add_column("Result")
    table.add_column("Best target", style="dim")
    table.add_column("Trust", justify="center")

    for objective in objectives:
        finding = report.finding(objective.id)
        if finding is None:
            continue
        best = finding.best
        if best:
            result = f"{len(finding.candidates)} candidate(s)"
            # Short class name keeps the table readable on a narrow terminal.
            target = f"{best.class_name.rsplit('.', 1)[-1]}.{best.method_name}"
            trust = _confidence_label(best.score)
        elif finding.detected_libraries:
            result = "SDK found, no hook"
            target = "-"
            trust = "[red]-[/red]"
        else:
            result = "not detected"
            target = "-"
            trust = "[red]-[/red]"
        table.add_row(objective.title, result, target, trust)

    console.print(table)

    if details:
        for objective in objectives:
            finding = report.finding(objective.id)
            if not finding or not finding.candidates:
                continue
            console.print(f"\n[bold]{escape(objective.title)}[/bold]")
            for candidate in finding.candidates[:4]:
                console.print(
                    f"  [cyan]{escape(candidate.signature)}[/cyan] "
                    f"[dim](score {candidate.score})[/dim]"
                )
                for reason in candidate.reasons:
                    console.print(f"      [dim]- {escape(reason)}[/dim]")

        for objective in objectives:
            finding = report.finding(objective.id)
            if not finding or finding.candidates or not finding.detected_libraries:
                continue
            console.print(f"\n[bold]{escape(objective.title)}[/bold]")
            console.print(
                "  [dim]The app bundles "
                + escape(", ".join(finding.detected_libraries))
                + ", but the method that decides is hidden (obfuscated, or the "
                "SDK keeps it private). Patching inside an SDK is not reliable, "
                "so it is not suggested.[/dim]"
            )

    for warning in report.warnings:
        console.print(f"[yellow]! {escape(warning)}[/yellow]")


def _print_next_steps(result, report_file: Path) -> None:
    if result.is_bundle:
        console.print(Panel(
            f"[bold green]Your patch bundle is ready[/bold green]\n\n"
            f"1. Copy [bold]{escape(str(result.path))}[/bold] to your phone.\n"
            f"2. Open [bold]Morphe Manager[/bold], import the bundle, choose the app.\n"
            f"3. Apply the patch, then reinstall the app when asked.\n"
            f"4. Something broken? Uninstall and reinstall the original APK: "
            f"that restores the unpatched app.\n\n"
            f"[dim]Plain-English report: {escape(str(report_file))}[/dim]",
            title="What to do now",
            border_style="green",
        ))
        return

    repair_note = ""
    repairs = getattr(result, "repairs", None) or []
    if repairs:
        repair_note = (
            "\n[yellow]Automatic repair:[/yellow] "
            + escape("; ".join(repairs))
            + "\n"
        )

    console.print(Panel(
        f"[bold yellow]Patch source written, bundle not compiled yet[/bold yellow]\n"
        f"[dim]{escape(_short_message(result.message))}[/dim]\n"
        f"{repair_note}\n"
        f"Everything is saved in [bold]{escape(str(result.path.parent))}[/bold].\n"
        "What is left to do:\n\n"
        + "\n".join(f"  {escape(line)}" for line in result.next_steps),
        title="Almost there",
        border_style="yellow",
    ))
    console.print(f"[dim]Plain-English report: {escape(str(report_file))}[/dim]")


def _write_report(
    output_dir: Path,
    report,
    plans: Sequence,
    result,
    checks: Sequence[Dict[str, object]],
) -> Path:
    from morphy_creator.core.plan import PatchPlan

    lines: List[str] = []
    info = report.info
    lines.append("MORPHY PATCH REPORT")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"App:        {info.package or 'unknown'}")
    lines.append(f"Version:    {info.version_name or '?'} ({info.version_code or '?'})")
    lines.append(f"Android:    {info.min_sdk or '?'}+")
    lines.append(f"File:       {info.path}")
    lines.append(f"Analysed:   {report.method_count} methods / {report.class_count} classes")
    if info.packers:
        lines.append(f"Protection: {', '.join(info.packers)}")
    lines.append("")

    for plan in plans:
        if not isinstance(plan, PatchPlan):
            continue
        lines.append(f"PATCH: {plan.title}   [{plan.confidence} confidence]")
        lines.append("-" * 60)
        lines.append(plan.description)
        lines.append("")
        for step in plan.steps:
            lines.append(f"  Method: {step.target.signature}")
            lines.append(f"  Change: {step.plain_action}")
            for reason in step.target.reasons:
                lines.append(f"  Why:    {reason}")
            verdict = step.target.fingerprint_verdict
            if verdict:
                lines.append(
                    f"  Match:  {verdict} "
                    f"({step.target.fingerprint_matches} method(s) matched)"
                )
            lines.append("")
        for note in plan.notes:
            lines.append(f"  Note:   {note}")
        if plan.notes:
            lines.append("")
        if plan.verify_hint:
            lines.append(f"  How to check: {plan.verify_hint}")
        else:
            lines.append("  How to check: verify by hand on the device.")
        if plan.limits:
            lines.append(f"  Limits: {plan.limits}")
        lines.append("")

    if report.warnings:
        lines.append("WARNINGS")
        lines.append("-" * 60)
        for warning in report.warnings:
            lines.append(f"* {warning}")
        lines.append("")

    if checks:
        lines.append("AUTOMATIC CHECKS")
        lines.append("-" * 60)
        for check in checks:
            status = "OK" if check.get("valid") else "ISSUES"
            lines.append(f"* {Path(str(check.get('file'))).name}: {status} (score {check.get('score')})")
            for error in check.get("errors", []) or []:
                lines.append(f"    - {error}")
        lines.append("")

    lines.append("HOW TO USE")
    lines.append("-" * 60)
    if result is not None and result.is_bundle:
        lines.append(f"1. Copy {result.path} to the phone.")
        lines.append("2. Open Morphe Manager and import the .mpp bundle.")
        lines.append("3. Select the app, apply the patch, reinstall when asked.")
    elif result is not None:
        lines.append("The patch code is written but not compiled yet.")
        lines.append(f"Details: {result.message}")
        for step in result.next_steps:
            lines.append(f"  {step}")
    else:
        lines.append("No bundle was produced. See the warnings above.")
    lines.append("")
    lines.append("Limits (please read):")
    lines.append("* Only decisions made inside the app can be patched.")
    lines.append("* Server-side checks, hardware attestation and encrypted code are out of reach.")
    lines.append("* Keep the original APK: reinstalling it restores the unpatched app.")
    lines.append("")

    path = output_dir / "REPORT.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _generate(
    apk: Path,
    objectives: Sequence[Objective],
    output_dir: Path,
    assume_yes: bool = False,
    show_details: bool = False,
    max_steps: int = 2,
) -> int:
    """Analysis -> plan -> Kotlin -> self-check -> bundle. Returns exit code."""
    from morphy_creator.core.analysis import analyse
    from morphy_creator.core.plan import dedupe_plans, plans_for_report
    from morphy_creator.core.verifier import PatchVerifier
    from morphy_creator.synthesizer.patch_writer import PatchWriter

    with console.status("[cyan]Reading the app...[/cyan]", spinner="dots"):
        try:
            report = analyse(apk, objectives, progress=lambda _m: None)
        except Exception as exc:  # noqa: BLE001 - shown to a non-technical user
            _friendly_error(
                f"Could not read this APK: {exc}",
                "Check that the file is complete (not still downloading) and that it is an Android app.",
            )
            return 2

    _show_apk_card(report.info)
    _show_findings(report, objectives, details=show_details)

    if not report.has_actionable_targets:
        console.print(
            "\n[yellow]I could not find anything to change for these goals.[/yellow]\n"
            "[dim]Try another goal, or choose 'a' next time to search with your own words.[/dim]"
        )
        return 3

    plans = dedupe_plans(plans_for_report(report, objectives, max_steps=max_steps))

    console.print("\n[bold]Plan[/bold]")
    for plan in plans:
        for line in plan.plain_summary():
            console.print(f"  {escape(line)}")

    if not assume_yes and not Confirm.ask("\nCreate these patches?", default=True):
        console.print("[dim]Nothing was written.[/dim]")
        return 0

    writer = PatchWriter(output_dir)
    written = []
    with console.status("[cyan]Writing the patch code...[/cyan]", spinner="dots"):
        for plan in plans:
            try:
                written.append(writer.write(plan))
            except Exception as exc:  # noqa: BLE001
                _friendly_error(f"Could not write {plan.title}: {exc}")
                return 4

    checks = [PatchVerifier.verify_patch_file(path) for path in written]
    for check in checks:
        name = Path(str(check["file"])).name
        if check["valid"]:
            console.print(f"[green]OK[/green] {name} (quality score {check['score']}/100)")
        else:
            console.print(f"[red]Issue[/red] {name}")
            for error in check["errors"]:
                console.print(f"    [red]- {escape(error)}[/red]")

    with console.status("[cyan]Packaging...[/cyan]", spinner="dots"):
        result = writer.build_bundle(written)

    report_file = _write_report(output_dir, report, plans, result, checks)
    console.print()
    _print_next_steps(result, report_file)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Morphy Patches Creator - build Morphe patches without writing code."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(wizard)


@cli.command()
@click.option("-o", "--output", default=str(DEFAULT_OUTPUT), help="Folder for the generated files")
@click.option("--max-targets", default=2, show_default=True, type=int, help="Methods to patch per goal")
def wizard(output: str, max_targets: int) -> None:
    """Guided assistant: answer a few questions, get a ready-to-install patch."""
    console.print(Panel.fit(
        "[bold cyan]Morphy Patch Wizard[/bold cyan]\n"
        "[dim]You do not need to know how to code. I will ask a few questions,\n"
        "read the app, and build the patch file for you.[/dim]",
        border_style="cyan",
    ))

    console.print("\n[bold]Step 1 of 4 - Which app?[/bold]")
    console.print("[dim]Drag the .apk file into this window, or paste its path.[/dim]")
    raw = Prompt.ask("APK path")
    apk = _resolve_apk(raw)
    if apk is None:
        return

    console.print("\n[bold]Step 2 of 4 - What should the patch do?[/bold]")
    objectives = _ask_objectives()

    console.print("\n[bold]Step 3 of 4 - Analysis and plan[/bold]")
    exit_code = _generate(apk, objectives, Path(output).expanduser(), max_targets=max_targets)

    if exit_code == 0:
        console.print("\n[bold]Step 4 of 4 - Done[/bold]")
    else:
        console.print(
            "\n[dim]Tip: run 'morphy-creator doctor' to check that everything is installed.[/dim]"
        )


@cli.command()
@click.argument("apk", type=click.Path(exists=True, dir_okay=False))
@click.option("--for", "objective_ids", required=True,
              help="Goals, e.g. ads,premium or 1,3 (see 'morphy-creator recipes')")
@click.option("-o", "--output", default=str(DEFAULT_OUTPUT), help="Folder for the generated files")
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation")
@click.option("--max-targets", default=2, show_default=True, type=int, help="Methods to patch per goal")
@click.option("--details", is_flag=True, help="Show every candidate and the evidence")
def create(apk: str, objective_ids: str, output: str, yes: bool, max_targets: int, details: bool) -> None:
    """Non-interactive patch creation (for scripts and power users)."""
    objectives = _parse_objective_flag(objective_ids)
    if not objectives:
        _friendly_error(
            f"No known goal in '{objective_ids}'.",
            "Use ids or numbers, for example: --for ads,premium or --for 1,3.",
        )
        raise SystemExit(2)
    raise SystemExit(
        _generate(Path(apk), objectives, Path(output).expanduser(), assume_yes=yes,
                  show_details=details, max_steps=max_targets)
    )


@cli.command()
@click.argument("apk", type=click.Path(exists=True, dir_okay=False))
@click.option("-p", "--prompt", required=True, help="What the patch should do, in plain words")
@click.option("-o", "--output", default=str(DEFAULT_OUTPUT), help="Folder for the generated files")
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation")
def auto(apk: str, prompt: str, output: str, yes: bool) -> None:
    """Describe the goal in plain words, get a patch (non-interactive)."""
    objectives = match_text(prompt)
    if not objectives:
        keywords = [word for word in prompt.replace(",", " ").split() if len(word) > 3]
        if not keywords:
            _friendly_error(
                "I did not understand the goal.",
                "Example: --prompt \"remove ads and allow screenshots\"",
            )
            raise SystemExit(2)
        objectives = [custom_objective(keywords)]
    raise SystemExit(_generate(Path(apk), objectives, Path(output).expanduser(), assume_yes=yes))


@cli.command()
@click.argument("apk", type=click.Path(exists=True, dir_okay=False))
@click.option("--for", "objective_ids", default="", help="Limit to some goals (default: analyse everything)")
@click.option("--details", is_flag=True, help="Show every candidate and the evidence")
def inspect(apk: str, objective_ids: str, details: bool) -> None:
    """Read an APK and explain what is patchable - no files are written."""
    from morphy_creator.core.analysis import analyse

    objectives = _parse_objective_flag(objective_ids) or list(OBJECTIVES)
    with console.status("[cyan]Reading the app...[/cyan]", spinner="dots"):
        report = analyse(Path(apk), objectives)
    _show_apk_card(report.info)
    _show_findings(report, objectives, details=details)


@cli.command()
@click.argument("apk", type=click.Path(exists=True, dir_okay=False))
@click.option("--goal", "goal_text", required=True, help="What you want to change, in plain words")
@click.option("--for", "objective_ids", default="", help="Limit to explicit goal ids (optional)")
@click.option("--json", "as_json", is_flag=True, help="Print the evidence dossier as JSON")
@click.option("--details", is_flag=True, help="Show calls, callers and every evidence line")
@click.option("--no-call-graph", is_flag=True, help="Skip the call graph (faster)")
@click.option("--max-candidates", default=4, show_default=True, type=int,
              help="Candidates to inspect per goal")
def investigate(apk: str, goal_text: str, objective_ids: str, as_json: bool,
                details: bool, no_call_graph: bool, max_candidates: int) -> None:
    """Explain the evidence behind a goal before any patch is written."""
    from morphy_creator.core.investigate import investigate as run_investigation

    objectives = _parse_objective_flag(objective_ids) or match_text(goal_text)
    if not objectives:
        keywords = [word for word in goal_text.replace(",", " ").split() if len(word) > 3]
        if not keywords:
            _friendly_error(
                "I did not understand the goal.",
                "Example: --goal \"unlock premium features\"",
            )
            raise SystemExit(2)
        objectives = [custom_objective(keywords)]

    with console.status("[cyan]Collecting evidence...[/cyan]", spinner="dots"):
        dossier = run_investigation(
            Path(apk),
            objectives,
            with_call_graph=not no_call_graph,
            max_candidates=max_candidates,
        )

    if as_json:
        click.echo(json.dumps(dossier, indent=2, ensure_ascii=False))
        return

    console.print(Panel.fit(
        f"[bold]{escape(str(dossier.get('package') or '?'))}[/bold]  "
        f"version {escape(str(dossier.get('version') or '?'))}\n"
        f"[dim]Goal: {escape(goal_text)}[/dim]",
        border_style="cyan",
    ))

    goals = dossier.get("goals") or []
    if not goals:
        console.print("[yellow]No goal was analysed.[/yellow]")
        return

    for goal in goals:
        console.print(f"\n[bold]{escape(str(goal['title']))}[/bold]  "
                      f"[dim]({goal['candidate_count']} candidate(s), "
                      f"confidence {goal['confidence']})[/dim]")
        recommended = goal.get("recommended")
        if recommended:
            console.print(
                f"  [green]Recommended:[/green] {escape(str(recommended['signature']))}  "
                f"[dim]({recommended['level']} evidence, {recommended['strategy']})[/dim]"
            )
        else:
            console.print(
                "  [red]Insufficient evidence:[/red] no candidate can be justified, "
                "so no patch would be generated."
            )

        rows = goal.get("candidates") or []
        if details:
            for row in rows:
                console.print(
                    f"\n  [bold]{escape(str(row['signature']))}[/bold]  "
                    f"[dim]score {row['score']}, {row['level']} evidence, "
                    f"fingerprint {row['fingerprint']['verdict']}[/dim]"
                )
                for line in row.get("evidence") or []:
                    console.print(f"    - {escape(str(line))}")
                if row.get("callers"):
                    console.print("    callers: " + escape(", ".join(row["callers"][:5])))
                if row.get("calls"):
                    console.print("    calls:   " + escape(", ".join(row["calls"][:5])))

        for note in goal.get("notes") or []:
            if note:
                console.print(f"  [yellow]Note:[/yellow] {escape(str(note))}")

    if details:
        console.print("\n[dim]Evidence is read from the APK. Nothing above is simulated.[/dim]")


@cli.command()
@click.argument("apk", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", default="./workspace", help="Extraction destination directory")
def unpack(apk: str, output: str) -> None:
    """Decompile the APK (resources + Smali) with Apktool."""
    from morphy_creator.adapters.apktool_adapter import ApktoolAdapter

    console.print(f"[bold blue]Unpacking:[/bold blue] {apk} -> {output}")
    if ApktoolAdapter().decode(Path(apk), Path(output)):
        console.print("[green]Manifest decoded, resources extracted, Smali disassembled.[/green]")
    else:
        _friendly_error("Apktool could not unpack this APK.", "Run 'morphy-creator doctor'.")


@cli.command()
@click.argument("bundle", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output", default="./merged_splits", help="Destination folder")
def merge(bundle: str, output: str) -> None:
    """Extract the base APK from a split bundle (.apkm, .xapk, .apks)."""
    from morphy_creator.core.split_merger import SplitApkMerger

    base = SplitApkMerger.extract_and_merge(Path(bundle), Path(output))
    if base:
        console.print(f"[green]Base APK extracted:[/green] {base}")
    else:
        _friendly_error("No APK found inside this bundle.")


@cli.command()
@click.argument("patch_file", type=click.Path(exists=True, dir_okay=False))
def verify(patch_file: str) -> None:
    """Check a generated patch file before using it."""
    from morphy_creator.core.verifier import PatchVerifier

    result = PatchVerifier.verify_patch_file(Path(patch_file))
    if result["valid"]:
        console.print(f"[bold green]OK[/bold green] (quality score {result['score']}/100)")
    else:
        console.print("[bold red]Issues found[/bold red]")
        for error in result["errors"]:
            console.print(f"  [red]- {escape(error)}[/red]")
    for warning in result["warnings"]:
        console.print(f"  [yellow]- {escape(warning)}[/yellow]")


@cli.command()
@click.argument("patches_dir", type=click.Path(exists=True, file_okay=False))
@click.option("-o", "--output", default="", help="Folder holding the project (default: same folder)")
def build(patches_dir: str, output: str) -> None:
    """Compile the generated patches into an installable .mpp bundle."""
    from morphy_creator.synthesizer.patch_writer import PatchWriter

    root = Path(patches_dir)
    files = sorted(root.glob("**/*.kt"))
    if not files:
        _friendly_error("No .kt patch file in this folder.", "Run the wizard first.")
        return

    writer = PatchWriter(Path(output) if output else root)
    with console.status("[cyan]Compiling... (this can take a few minutes)[/cyan]", spinner="dots"):
        result = writer.build_bundle(files)

    if result.is_bundle:
        console.print(f"[bold green]Bundle ready:[/bold green] {result.path}")
    else:
        repairs = getattr(result, "repairs", None) or []
        repair_note = (
            "\n[yellow]Automatic repair:[/yellow] " + escape("; ".join(repairs)) + "\n"
            if repairs else ""
        )
        console.print(Panel(
            f"[bold yellow]Could not compile the bundle[/bold yellow]\n"
            f"[dim]{escape(_short_message(result.message))}[/dim]\n"
            f"{repair_note}\n"
            + "\n".join(f"  {escape(line)}" for line in result.next_steps),
            title="What is missing",
            border_style="yellow",
        ))


@cli.command()
def doctor() -> None:
    """Check that everything needed is installed and working."""
    from morphy_creator.doctor import MorphyDoctor

    MorphyDoctor.run_diagnostics()


@cli.command()
def recipes() -> None:
    """List the goals you can ask for."""
    table = Table(title="Supported goals")
    table.add_column("#", style="cyan", justify="right")
    table.add_column("id", style="magenta")
    table.add_column("Goal", style="white")
    table.add_column("What it does", style="dim")
    for index, objective in enumerate(OBJECTIVES, start=1):
        table.add_row(str(index), objective.id, objective.title, objective.tagline)
    console.print(table)
    console.print("[dim]Usage: morphy-creator create app.apk --for ads,premium[/dim]")


@cli.command()
def mcp() -> None:
    """Start the MCP server (for AI assistants)."""
    from morphy_creator.mcp_server import run_stdio_server

    run_stdio_server()


@cli.command()
def about() -> None:
    """Credits and upstream projects."""
    console.print(Panel.fit(
        "[bold cyan]Morphy Patches Creator[/bold cyan]\n"
        "[italic]Plain-English goals to installable Morphe patches[/italic]\n\n"
        "[bold yellow]Targets and uses:[/bold yellow]\n"
        "1. [bold green]Morphe[/bold green] - patcher API and build toolchain\n"
        "   https://github.com/MorpheApp\n"
        "2. [bold green]Apktool[/bold green] - Connor Tumbleson & Ryszard Wisniewski\n"
        "   https://github.com/iBotPeaches/Apktool (optional unpack)\n"
        "3. [bold green]JADX[/bold green] - @skylot\n"
        "   https://github.com/skylot/jadx (optional Java view)\n"
        "4. [bold green]Rich[/bold green] and [bold green]Click[/bold green] - terminal UI\n\n"
        "[dim]DEX and binary-manifest parsing is original, dependency-free code.\n"
        "It reads the app directly: no Androguard, no external analyzer.[/dim]",
        title="About",
    ))


def main() -> None:
    """Entry point with a friendly error screen instead of a traceback."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[dim]Cancelled.[/dim]")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        if "--debug" in sys.argv:
            raise
        _friendly_error(
            str(exc),
            "Run the same command with --debug to see the technical details, "
            "or 'morphy-creator doctor' to check your installation.",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
