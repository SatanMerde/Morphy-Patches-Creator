"""
Fingerprint uniqueness: does the generated matcher actually point at one method?

A patch is only as good as its fingerprint. If the class/name/descriptor match
several methods, Morphe's ``match()`` becomes unpredictable; if a string anchor
is used by thousands of methods, the fingerprint will break on the next update.
This module checks both against the same APK the candidate came from.

The check is free during analysis: the scanner already decoded the methods, so
the reuse pass only walks cached bodies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence

# Above this many methods sharing an anchor, the text is too generic to be a
# stable fingerprint signal.
GENERIC_ANCHOR_THRESHOLD = 200


@dataclass
class FingerprintCheck:
    verdict: str                 # unique | ambiguous | missing | generic-anchor
    exact_matches: int
    signature_matches: int
    anchor_reuse: Dict[str, int] = field(default_factory=dict)
    detail: str = ""

    @property
    def unique(self) -> bool:
        return self.verdict == "unique"

    def to_dict(self) -> Dict[str, object]:
        return {
            "verdict": self.verdict,
            "exact_matches": self.exact_matches,
            "signature_matches": self.signature_matches,
            "anchor_reuse": self.anchor_reuse,
            "detail": self.detail,
        }


def _anchors(candidate: object) -> List[str]:
    strings: Sequence[str] = getattr(candidate, "strings", ()) or ()
    return [text for text in strings if text and len(text) >= 3][:3]


def check_candidate(dex_files: Iterable[object], candidate: object) -> FingerprintCheck:
    """Counts how many methods the rendered fingerprint would match."""
    class_descriptor = getattr(candidate, "class_descriptor", "")
    method_name = getattr(candidate, "method_name", "")
    descriptor = getattr(candidate, "method_descriptor", "")
    anchors = _anchors(candidate)

    signature_matches = 0
    exact_matches = 0
    for dex in dex_files:
        for method in dex.iter_methods():  # type: ignore[attr-defined]
            if method.class_descriptor != class_descriptor:  # type: ignore[attr-defined]
                continue
            if method.name != method_name:  # type: ignore[attr-defined]
                continue
            if method.descriptor != descriptor:  # type: ignore[attr-defined]
                continue
            signature_matches += 1
            strings = method.uses_strings()  # type: ignore[attr-defined]
            if all(anchor in strings for anchor in anchors):
                exact_matches += 1

    reuse = {anchor: 0 for anchor in anchors}
    if anchors:
        for dex in dex_files:
            for method in dex.iter_methods():  # type: ignore[attr-defined]
                code = getattr(method, "_code", None)
                if code is None:
                    continue
                for anchor in anchors:
                    if anchor in code.strings:
                        reuse[anchor] += 1

    if exact_matches == 0:
        verdict = "missing"
        detail = (
            "The fingerprint does not match any method in this APK anymore. "
            "The candidate will be discarded."
        )
    elif exact_matches > 1:
        verdict = "ambiguous"
        detail = (
            f"The fingerprint matches {exact_matches} methods. "
            "Add a distinctive string or a literal filter before using it."
        )
    elif anchors and max(reuse.values()) > GENERIC_ANCHOR_THRESHOLD:
        worst = max(reuse, key=reuse.get)
        verdict = "generic-anchor"
        detail = (
            f"The anchor '{worst}' is used by {reuse[worst]} methods; "
            "it may stop identifying this method after an update."
        )
    else:
        verdict = "unique"
        detail = "The fingerprint matches exactly one method in this APK."

    return FingerprintCheck(
        verdict=verdict,
        exact_matches=exact_matches,
        signature_matches=signature_matches,
        anchor_reuse=reuse,
        detail=detail,
    )


def check_report(report: object, dex_files: Iterable[object]) -> None:
    """Annotates every candidate and drops those that no longer match."""
    dex_list = list(dex_files)
    findings = getattr(report, "findings", {})
    warnings: List[str] = getattr(report, "warnings", [])

    for finding in findings.values():
        kept = []
        dropped = 0
        for candidate in finding.candidates:
            check = check_candidate(dex_list, candidate)
            candidate.fingerprint_verdict = check.verdict
            candidate.fingerprint_matches = check.exact_matches
            candidate.anchor_reuse = max(check.anchor_reuse.values(), default=0)
            if check.verdict == "missing":
                dropped += 1
                continue
            kept.append(candidate)
        if dropped:
            warnings.append(
                f"{dropped} candidate(s) for '{finding.objective_id}' were discarded: "
                "their fingerprint no longer matches the APK."
            )
        finding.candidates = kept
