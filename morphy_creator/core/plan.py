"""
Patch planning: turns analysis findings into a concrete, reviewable plan.

A plan is what the user validates in the wizard ("I will make these 2 methods
answer 'yes'") before any Kotlin is written. Keeping it separate from code
generation means the plain-English preview and the generated source can never
disagree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from morphy_creator.core.analysis import AnalysisReport, ObjectiveFinding, TargetCandidate
from morphy_creator.presets.objectives import (
    STRATEGY_LABELS,
    Objective,
    choose_strategy,
)


@dataclass
class PatchStep:
    """One method to change, with the reason shown to the user."""

    target: TargetCandidate
    strategy: str

    @property
    def plain_action(self) -> str:
        return STRATEGY_LABELS.get(self.strategy, self.strategy)

    def to_dict(self) -> Dict[str, object]:
        data = self.target.to_dict()
        data["action"] = self.strategy
        data["action_plain"] = self.plain_action
        return data


@dataclass
class PatchPlan:
    """Everything needed to render one Kotlin patch class."""

    package_name: str
    app_package: str
    app_version: str
    objective_id: str
    title: str
    description: str
    class_name: str
    steps: List[PatchStep] = field(default_factory=list)
    confidence: str = "medium"
    notes: List[str] = field(default_factory=list)
    verify_hint: str = ""
    limits: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.steps

    def plain_summary(self) -> List[str]:
        lines = [f"{self.title} - {self.description}"]
        for step in self.steps:
            lines.append(f"  * {step.target.signature}: {step.plain_action}")
        return lines


def kotlin_class_name(title: str) -> str:
    """``Remove ads`` -> ``RemoveAdsPatch`` (always a valid Kotlin identifier)."""
    words = re.findall(r"[A-Za-z0-9]+", title)
    name = "".join(word[:1].upper() + word[1:] for word in words) or "Custom"
    if name[0].isdigit():
        name = f"Patch{name}"
    if not name.endswith("Patch"):
        name += "Patch"
    return name


def snake_case(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    return "_".join(words) or "patch"


def confidence_of(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 6:
        return "medium"
    return "low"


def plan_for_finding(
    report: AnalysisReport,
    finding: ObjectiveFinding,
    objective: Objective,
    max_steps: int = 2,
    exclude: Optional[Sequence[str]] = None,
) -> PatchPlan:
    """Builds a plan from the ranked candidates of one objective."""
    excluded = set(exclude or ())
    steps: List[PatchStep] = []
    for candidate in finding.candidates:
        if candidate.signature in excluded:
            continue
        strategy = candidate.strategy or choose_strategy(objective, candidate.return_type)
        steps.append(PatchStep(target=candidate, strategy=strategy))
        if len(steps) >= max_steps:
            break

    best_score = max((step.target.score for step in steps), default=0)
    plan = PatchPlan(
        package_name=snake_case(objective.id),
        app_package=report.info.package,
        app_version=report.info.version_name,
        objective_id=objective.id,
        title=objective.title,
        description=objective.explanation.split(".")[0].strip() + ".",
        class_name=kotlin_class_name(objective.title),
        steps=steps,
        confidence=confidence_of(best_score),
        verify_hint=objective.verify_hint,
        limits=objective.limits,
    )

    if not steps:
        plan.notes.append(
            "This app does not expose a hook for this objective. "
            "Nothing will be generated for it."
        )
    elif plan.confidence == "low":
        plan.notes.append(
            "Low confidence: the suggested method may not be the right one. "
            "Test the app carefully, or try another objective."
        )

    return plan


def plans_for_report(
    report: AnalysisReport,
    objectives: Sequence[Objective],
    max_steps: int = 2,
    only_high_confidence: bool = False,
) -> List[PatchPlan]:
    plans: List[PatchPlan] = []
    for objective in objectives:
        finding = report.finding(objective.id)
        if finding is None:
            continue
        plan = plan_for_finding(report, finding, objective, max_steps=max_steps)
        if only_high_confidence and plan.confidence == "low":
            continue
        plans.append(plan)
    return plans


def dedupe_plans(plans: Sequence[PatchPlan]) -> List[PatchPlan]:
    """Two objectives may target the same method; patch it only once."""
    seen: set = set()
    unique: List[PatchPlan] = []
    for plan in plans:
        steps = [step for step in plan.steps if step.target.signature not in seen]
        for step in steps:
            seen.add(step.target.signature)
        if steps:
            plan.steps = steps
            unique.append(plan)
    return unique
