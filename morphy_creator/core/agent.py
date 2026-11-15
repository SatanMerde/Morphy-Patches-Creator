"""
Programmatic entry point (used by the CLI, the MCP server and the tests).

``PatchAgent.create`` is the whole pipeline in one call:

    analyse APK -> rank targets -> build a plan -> render Kotlin ->
    self-check -> package
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from morphy_creator.core.analysis import AnalysisReport, analyse
from morphy_creator.core.plan import PatchPlan, dedupe_plans, plans_for_report
from morphy_creator.core.verifier import PatchVerifier
from morphy_creator.presets.objectives import Objective
from morphy_creator.synthesizer.patch_writer import BuildResult, PatchWriter


@dataclass
class AgentResult:
    report: AnalysisReport
    plans: List[PatchPlan]
    patch_files: List[Path]
    checks: List[Dict[str, object]]
    build: BuildResult

    def to_dict(self) -> Dict[str, object]:
        return {
            "app": self.report.info.package,
            "version": self.report.info.version_name,
            "plans": [
                {
                    "goal": plan.objective_id,
                    "title": plan.title,
                    "confidence": plan.confidence,
                    "steps": [step.to_dict() for step in plan.steps],
                }
                for plan in self.plans
            ],
            "patch_files": [str(path) for path in self.patch_files],
            "checks": self.checks,
            "bundle": {
                "kind": self.build.kind,
                "path": str(self.build.path),
                "message": self.build.message,
            },
            "next_steps": self.build.next_steps,
            "warnings": self.report.warnings,
        }


class PatchAgent:
    """Zero-interaction patch creation."""

    def create(
        self,
        apk_path: Path,
        objectives: Sequence[Objective],
        output_dir: Path,
        max_steps: int = 2,
        allow_network: bool = True,
    ) -> AgentResult:
        report = analyse(Path(apk_path), objectives)
        plans = dedupe_plans(plans_for_report(report, objectives, max_steps=max_steps))

        writer = PatchWriter(Path(output_dir))
        written = [writer.write(plan) for plan in plans]
        checks = [PatchVerifier.verify_patch_file(path) for path in written]
        build = writer.build_bundle(written, allow_network=allow_network)

        return AgentResult(
            report=report,
            plans=plans,
            patch_files=written,
            checks=checks,
            build=build,
        )


# Backwards-compatible name used by the old test suite / scripts.
AutonomousPatchAgent = PatchAgent
