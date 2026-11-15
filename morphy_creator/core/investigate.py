"""
Evidence-first investigation for one goal.

The scanner answers *which methods look like the feature*. This module answers
the next question an agent or a human must answer before patching: **what can be
shown as proof?** Every entry is read from the APK: a preference key, a call
edge, a text constant, a blocking literal. Nothing is simulated, and a
candidate with no hard evidence is reported as such.

The output is a plain dictionary so the CLI can render it and an AI assistant
can consume it over MCP without guessing at shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from morphy_creator.core.analysis import AnalysisReport, TargetCandidate, analyse
from morphy_creator.core.plan import plan_for_finding
from morphy_creator.core.verifier import GENERIC_ANCHORS
from morphy_creator.core.xrefs import CallGraph
from morphy_creator.presets.objectives import Objective

# How much independent proof backs a candidate.
LEVEL_STRONG = "strong"
LEVEL_MODERATE = "moderate"
LEVEL_WEAK = "weak"
LEVEL_NONE = "none"

_LEVEL_RANK = {LEVEL_STRONG: 3, LEVEL_MODERATE: 2, LEVEL_WEAK: 1, LEVEL_NONE: 0}


@dataclass
class CandidateEvidence:
    """Everything that can be said about one candidate, with its source."""

    signature: str
    class_descriptor: str
    method_name: str
    method_descriptor: str
    return_type: str
    score: int
    strategy: str
    reasons: List[str] = field(default_factory=list)
    preference_keys: List[str] = field(default_factory=list)
    preference_source: str = ""
    strings: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    literals: List[int] = field(default_factory=list)
    callers: List[str] = field(default_factory=list)
    callees: List[str] = field(default_factory=list)
    fingerprint_verdict: str = ""
    fingerprint_matches: int = 0
    evidence: List[str] = field(default_factory=list)
    level: str = LEVEL_NONE

    @property
    def patchable(self) -> bool:
        return self.level in (LEVEL_STRONG, LEVEL_MODERATE)

    def to_dict(self) -> Dict[str, object]:
        return {
            "signature": self.signature,
            "class": self.class_descriptor,
            "method": self.method_name,
            "descriptor": self.method_descriptor,
            "return_type": self.return_type,
            "score": self.score,
            "strategy": self.strategy,
            "level": self.level,
            "patchable": self.patchable,
            "evidence": self.evidence,
            "reasons": self.reasons,
            "preference_keys": self.preference_keys,
            "preference_source": self.preference_source,
            "strings": self.strings[:6],
            "calls": self.calls[:8],
            "literals": self.literals[:6],
            "callers": self.callers[:10],
            "callees": self.callees[:10],
            "fingerprint": {
                "verdict": self.fingerprint_verdict,
                "matches": self.fingerprint_matches,
            },
        }


def _distinctive_strings(candidate: TargetCandidate) -> List[str]:
    return [
        text for text in candidate.strings
        if len(text) >= 4 and text.lower() not in GENERIC_ANCHORS
    ][:4]


def _classify(candidate: TargetCandidate) -> tuple[str, List[str]]:
    """Returns (level, human-readable evidence lines)."""
    evidence: List[str] = []
    level = LEVEL_NONE

    if candidate.preference_source == "method" and candidate.preference_keys:
        keys = ", ".join(f"'{key}'" for key in candidate.preference_keys[:3])
        evidence.append(f"the method itself reads the preference {keys}")
        level = LEVEL_STRONG
    elif candidate.preference_source == "class" and candidate.preference_keys:
        keys = ", ".join(f"'{key}'" for key in candidate.preference_keys[:3])
        evidence.append(f"its class owns the preference {keys} and exposes it through this getter")
        level = LEVEL_MODERATE

    if candidate.literals:
        rendered = ", ".join(f"0x{value:x}" for value in candidate.literals[:4])
        evidence.append(f"it uses the blocking literal {rendered}")
        level = LEVEL_STRONG

    name_reasons = [reason for reason in candidate.reasons if reason.startswith("method name matches")]
    if name_reasons:
        evidence.append(name_reasons[0])
        level = LEVEL_STRONG

    strings = _distinctive_strings(candidate)
    if strings:
        rendered = ", ".join(f"'{text}'" for text in strings[:3])
        evidence.append(f"its body contains {rendered}")
        if level == LEVEL_NONE:
            level = LEVEL_MODERATE

    library_reasons = [reason for reason in candidate.reasons if reason.startswith("calls ")]
    if library_reasons:
        evidence.append(library_reasons[0])
        if level == LEVEL_NONE:
            level = LEVEL_MODERATE

    if level == LEVEL_NONE and candidate.reasons:
        # Only weak context is left (class name, return type, UI hint).
        evidence.append(candidate.reasons[0])
        level = LEVEL_WEAK

    return level, evidence


def _enrich(
    candidate: TargetCandidate,
    graph: Optional[CallGraph],
    max_edges: int = 12,
) -> CandidateEvidence:
    level, evidence = _classify(candidate)
    callers: List[str] = []
    callees: List[str] = []
    if graph is not None:
        callers = graph.callers(candidate.full_name, include_overrides=False)[:max_edges]
        callees = graph.callees(candidate.full_name)[:max_edges]

    return CandidateEvidence(
        signature=candidate.signature,
        class_descriptor=candidate.class_descriptor,
        method_name=candidate.method_name,
        method_descriptor=candidate.method_descriptor,
        return_type=candidate.return_type,
        score=candidate.score,
        strategy=candidate.strategy,
        reasons=list(candidate.reasons),
        preference_keys=list(candidate.preference_keys),
        preference_source=candidate.preference_source,
        strings=list(candidate.strings),
        calls=list(candidate.calls),
        literals=list(candidate.literals),
        callers=callers,
        callees=callees,
        fingerprint_verdict=candidate.fingerprint_verdict,
        fingerprint_matches=candidate.fingerprint_matches,
        evidence=evidence,
        level=level,
    )


def investigate(
    apk_path: Path | str,
    objectives: Sequence[Objective],
    *,
    with_call_graph: bool = True,
    max_candidates: int = 4,
) -> Dict[str, object]:
    """Analyses the APK and returns a per-goal evidence dossier."""
    report: AnalysisReport = analyse(Path(apk_path), objectives)

    graph: Optional[CallGraph] = None
    if with_call_graph:
        from morphy_creator.core.apk import ApkContainer

        container = ApkContainer.open(Path(apk_path))
        try:
            graph = CallGraph.build(container.dex_files())
        finally:
            container.close()

    goals: List[Dict[str, object]] = []
    for objective in objectives:
        finding = report.findings.get(objective.id)
        if finding is None:
            continue
        candidates = [_enrich(candidate, graph) for candidate in finding.candidates[:max_candidates]]
        candidates.sort(
            key=lambda item: (_LEVEL_RANK[item.level], item.score), reverse=True
        )
        patchable = [item for item in candidates if item.patchable]
        plan = plan_for_finding(report, finding, objective)
        goals.append(
            {
                "objective": objective.id,
                "title": objective.title,
                "candidate_count": len(finding.candidates),
                "patchable_count": len(patchable),
                "confidence": plan.confidence,
                "recommended": {
                    "signature": patchable[0].signature,
                    "level": patchable[0].level,
                    "strategy": patchable[0].strategy,
                } if patchable else None,
                "candidates": [item.to_dict() for item in candidates],
                "notes": list(plan.notes),
                "verify_hint": plan.verify_hint,
                "limits": plan.limits,
            }
        )

    return {
        "apk": str(apk_path),
        "package": report.info.package,
        "version": report.info.version_name,
        "obfuscation_ratio": round(report.obfuscation_ratio, 3),
        "warnings": list(report.warnings),
        "goals": goals,
    }
