"""
Real static analysis engine.

A single pass over the app's DEX bytecode scores every method against the
selected objectives. The output is a short, ranked list of concrete targets
with the evidence that earned them their score, so a non-technical user can
see *why* a method was picked and a developer can double-check it.

No network access, no Android SDK, no external tool: this runs on the APK
itself in a couple of seconds.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

from morphy_creator.core.apk import ApkContainer, ApkInfo
from morphy_creator.core.dex import (
    ACC_BRIDGE,
    ACC_SYNTHETIC,
    ClassInfo,
    DexFile,
    MethodCode,
    MethodInfo,
    looks_like_obfuscated,
)
from morphy_creator.core.fingerprint import check_report
from morphy_creator.core.preferences import PreferenceEvidence, PreferenceIndex
from morphy_creator.presets.objectives import (
    STRATEGY_DROP_FLAG,
    Objective,
    choose_strategy,
)

MAX_TARGETS_PER_OBJECTIVE = 6

# Packages that ship inside almost every app and are never the app's own
# decision point. Candidates there are demoted, not dropped.
_VENDORED_PACKAGES = (
    "androidx.", "android.", "kotlin", "kotlinx.", "java.", "javax.",
    "com.google.android.material.", "com.google.android.gms.", "com.google.firebase.",
    "com.squareup.", "okhttp3.", "okio.", "retrofit2.", "io.reactivex.",
    "org.apache.", "com.fasterxml.", "com.dropbox.", "com.microsoft.",
    "org.bouncycastle.", "com.bea.xml.", "org.json.", "org.xmlpull.",
    "com.google.gson.", "io.grpc.", "com.google.protobuf.",
    # Ads, billing and monetisation SDKs: patching their internals is not a
    # reliable way to change the app's own decision.
    "com.facebook.",
    "com.facebook.ads.", "com.facebook.appevents.", "com.facebook.gamingservices.",
    "com.facebook.react.", "com.android.billingclient.", "com.revenuecat.",
    "com.adapty.", "com.qonversion.", "io.purchasely.", "com.pairip.",
    "com.inmobi.", "com.adjust.", "com.appsflyer.", "com.razorpay.",
    "com.chartboost.", "com.applovin.", "com.unity3d.ads.", "com.ironsource.",
    "com.mopub.", "com.adcolony.", "com.vungle.", "com.mintegral.",
    # Telemetry, feature-flag and logging infrastructure.
    "com.statsig.", "com.tiledmedia.", "org.slf4j.", "org.apache.logging.",
    "ch.qos.logback.",
    # TikTok SDK internals (analytics + in-app billing proxy) bundled in other apps.
    "com.tiktok.appevents.", "com.tiktok.iap.", "com.tiktok.monitoring.",
)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Words that turn a method name into a *display helper* for a feature rather
# than the feature's own decision: ``getSubscriptionHint`` shows a banner,
# ``hasSubscription`` gates the feature. Only goals that ask "is this true?"
# apply the penalty (see ``Objective.penalise_ui_names``).
_UI_NAME_TOKENS = frozenset({
    "hint", "banner", "toast", "snackbar", "tooltip", "badge",
    "prompt", "upsell", "onboarding", "placeholder", "widget", "view",
    "layout", "render", "drawer",
})

# Object-protocol and callback names. They can legitimately contain an SDK call
# (an analytics ``onClick``), but for goals that need real feature context they
# are plumbing, not the decision itself.
_GENERIC_METHOD_NAMES = frozenset({
    "equals", "hashCode", "toString", "clone", "compareTo", "invoke",
    "accept", "apply", "get", "call", "run", "iterator",
})


def _tokens(name: str) -> List[str]:
    """``isAdEnabled`` -> ``["is", "ad", "enabled"]`` (also splits packages)."""
    parts: List[str] = []
    for chunk in re.split(r"[.$_/\s]+", name):
        if not chunk:
            continue
        parts.extend(_CAMEL_BOUNDARY.sub("_", chunk).lower().split("_"))
    return [part for part in parts if part]


def _keyword_matches(keyword: str, tokens: List[str], max_join: int = 5) -> bool:
    """Matches a lowercase keyword against consecutive camelCase tokens.

    This is what stops ``isAdded`` from matching the keyword ``isad`` while
    still matching ``isAdEnabled``.
    """
    wanted = keyword.lower().replace("_", "")
    if not wanted:
        return False
    count = len(tokens)
    for start in range(count):
        joined = ""
        for end in range(start, min(start + max_join, count)):
            joined += tokens[end]
            if joined == wanted:
                return True
            if len(joined) >= len(wanted):
                break
    return False


def _joined_index(tokens: List[str], max_join: int = 5) -> set:
    """All concatenations of up to ``max_join`` consecutive tokens.

    Built once per class/method so keyword matching becomes a set lookup
    instead of a nested loop (this is the difference between 40s and 4s on a
    large APK).
    """
    joined: set = set()
    count = len(tokens)
    for start in range(count):
        accumulator = ""
        for end in range(start, min(start + max_join, count)):
            accumulator += tokens[end]
            joined.add(accumulator)
    return joined


def _match_any(keywords: Sequence[str], index: set) -> List[str]:
    return [keyword for keyword in keywords if keyword.lower().replace("_", "") in index]


@dataclass
class TargetCandidate:
    """A method that plausibly controls the behaviour the user wants to change."""

    objective_id: str
    class_name: str
    class_descriptor: str
    method_name: str
    method_descriptor: str
    return_type: str
    access_flags: int
    score: int
    strategy: str
    strings: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
    opcodes: List[str] = field(default_factory=list)
    literals: List[int] = field(default_factory=list)
    literal_sites: List[tuple] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    dex_file: str = ""
    # Preference keys that made this method suspicious (survives obfuscation).
    preference_keys: List[str] = field(default_factory=list)
    preference_source: str = ""
    # Fingerprint uniqueness against the APK the candidate came from.
    fingerprint_verdict: str = ""
    fingerprint_matches: int = 1
    anchor_reuse: int = 0

    @property
    def signature(self) -> str:
        return f"{self.class_name}.{self.method_name}"

    @property
    def full_name(self) -> str:
        """DEX reference: ``Lcom/foo/Bar;->a()Z`` (used by the call graph)."""
        return f"{self.class_descriptor}->{self.method_name}{self.method_descriptor}"

    def to_dict(self) -> Dict[str, object]:
        return {
            "objective": self.objective_id,
            "class": self.class_name,
            "method": self.method_name,
            "descriptor": self.method_descriptor,
            "return_type": self.return_type,
            "score": self.score,
            "strategy": self.strategy,
            "strings": self.strings,
            "calls": self.calls[:8],
            "literals": self.literals[:8],
            "reasons": self.reasons,
            "preference_keys": self.preference_keys,
            "preference_source": self.preference_source,
            "fingerprint": {
                "verdict": self.fingerprint_verdict,
                "matches": self.fingerprint_matches,
                "anchor_reuse": self.anchor_reuse,
            },
        }


@dataclass
class ObjectiveFinding:
    objective_id: str
    title: str
    candidates: List[TargetCandidate] = field(default_factory=list)
    signals: List[str] = field(default_factory=list)
    detected_libraries: List[str] = field(default_factory=list)
    present: bool = False

    @property
    def best(self) -> Optional[TargetCandidate]:
        return self.candidates[0] if self.candidates else None

    def summary(self) -> str:
        if not self.present and not self.candidates:
            return "Not detected in this app."
        if not self.candidates:
            library_note = ", ".join(self.detected_libraries[:3])
            return f"Feature detected ({library_note}) but no usable hook was found."
        return f"{len(self.candidates)} candidate(s), best confidence {self.candidates[0].score}."


@dataclass
class AnalysisReport:
    info: ApkInfo
    findings: Dict[str, ObjectiveFinding]
    method_count: int = 0
    class_count: int = 0
    obfuscation_ratio: float = 0.0
    warnings: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def finding(self, objective_id: str) -> Optional[ObjectiveFinding]:
        return self.findings.get(objective_id)

    def all_candidates(self) -> List[TargetCandidate]:
        found: List[TargetCandidate] = []
        for finding in self.findings.values():
            found.extend(finding.candidates)
        return found

    @property
    def has_actionable_targets(self) -> bool:
        return any(finding.candidates for finding in self.findings.values())


ProgressCallback = Callable[[str], None]


def analyse(
    apk_path: Path,
    objectives: Sequence[Objective],
    progress: Optional[ProgressCallback] = None,
    max_targets: int = MAX_TARGETS_PER_OBJECTIVE,
) -> AnalysisReport:
    """Scans the APK and returns ranked targets for every requested objective."""

    notify = progress or (lambda _message: None)

    notify("Opening the APK...")
    container = ApkContainer.open(Path(apk_path))
    try:
        info = container.info
        if info.is_protected:
            notify(f"Protection detected: {', '.join(info.packers)}")

        notify(f"Reading {len(info.dex_files)} DEX file(s)...")
        dex_files = container.dex_files()
        if not dex_files:
            raise ValueError(
                "No DEX file found inside this APK. It may be a split bundle "
                "(use 'merge' first) or the code is encrypted by a packer."
            )

        findings: Dict[str, ObjectiveFinding] = {}
        for objective in objectives:
            findings[objective.id] = ObjectiveFinding(
                objective_id=objective.id, title=objective.title
            )

        libraries: Dict[str, List[str]] = {o.id: [] for o in objectives}
        sdk_packages = _sdk_packages(objectives)
        preference_index = (
            PreferenceIndex.build(dex_files)
            if any(objective.trace_preference_keys for objective in objectives)
            else None
        )
        class_count = 0
        method_count = 0
        obfuscated_classes = 0

        for dex_index, dex in enumerate(dex_files, start=1):
            notify(f"Scanning {dex.name} ({dex_index}/{len(dex_files)})...")
            libraries_found = _detect_libraries(dex, objectives)
            for objective_id, hits in libraries_found.items():
                for hit in hits:
                    if hit not in libraries[objective_id]:
                        libraries[objective_id].append(hit)
                if hits:
                    findings[objective_id].present = True
                    findings[objective_id].detected_libraries = libraries[objective_id]

            for cls in dex.classes:
                class_count += 1
                if looks_like_obfuscated(cls.java_name.rsplit(".", 1)[-1]):
                    obfuscated_classes += 1
                method_count += _scan_class(
                    dex, cls, objectives, findings, max_targets, sdk_packages,
                    preference_index,
                )

        report = AnalysisReport(
            info=info,
            findings=findings,
            method_count=method_count,
            class_count=class_count,
            obfuscation_ratio=(obfuscated_classes / class_count) if class_count else 0.0,
        )

        _finalise(report, objectives)
        # The scanner keeps decoded bodies cached, so this pass is cheap: it
        # verifies that every fingerprint still targets exactly one method.
        check_report(report, dex_files)
        return report
    finally:
        container.close()


def _detect_libraries(dex: DexFile, objectives: Sequence[Objective]) -> Dict[str, List[str]]:
    """Finds advertising/analytics/billing SDKs by their class package names."""
    found: Dict[str, List[str]] = {objective.id: [] for objective in objectives}
    descriptors = [cls.descriptor for cls in dex.classes]

    for objective in objectives:
        for marker in objective.library_markers:
            for descriptor in descriptors:
                if marker in descriptor:
                    package = marker.replace("/", ".")
                    if package not in found[objective.id]:
                        found[objective.id].append(package)
                    break
    return found


def _sdk_packages(objectives: Sequence[Objective]) -> tuple:
    """Package prefixes of every SDK the selected goals look for.

    A method *inside* such a package is not the app's own decision: calling the
    SDK is tautological there. Those classes are treated like vendored code, so
    they are demoted and cannot satisfy "I call a known SDK" on their own.
    """
    return tuple(
        sorted({
            marker.replace("/", ".") + "."
            for objective in objectives
            for marker in objective.library_markers
        })
    )


def _scan_class(
    dex: DexFile,
    cls: ClassInfo,
    objectives: Sequence[Objective],
    findings: Dict[str, ObjectiveFinding],
    max_targets: int,
    sdk_packages: Sequence[str] = (),
    preference_index: Optional[PreferenceIndex] = None,
) -> int:
    """Scores every method of a class; returns how many methods were inspected."""
    inspected = 0
    class_name = cls.java_name
    class_index = _joined_index(_tokens(class_name))
    class_hits = {
        objective.id: _match_any(objective.class_keywords, class_index)
        for objective in objectives
    }
    vendored = class_name.startswith(_VENDORED_PACKAGES) or class_name.startswith(
        sdk_packages
    )

    for method in cls.methods:
        if not method.has_body:
            continue
        inspected += 1

        if method.name in ("<init>", "<clinit>"):
            continue

        # Compiler-generated accessors (``access$getX``) and bridge methods are
        # never the app's own decision point.
        if method.access_flags & (ACC_SYNTHETIC | ACC_BRIDGE):
            continue

        method_tokens = _tokens(method.name)
        method_index = _joined_index(method_tokens)
        ui_name = any(token in _UI_NAME_TOKENS for token in method_tokens)
        name_hits = {
            objective.id: _match_any(objective.method_keywords, method_index)
            for objective in objectives
        }

        # Only return types the generated code can rewrite (Morphe's returnEarly
        # covers primitives, void and String). Checking this before decoding the
        # bytecode is what keeps the full scan fast.
        return_type = method.return_type
        if return_type.startswith("[") or (
            return_type.startswith("L") and return_type != "Ljava/lang/String;"
        ):
            continue

        code = method.code()
        if code is None or not code.complete:
            continue

        pref_evidence = (
            preference_index.evidence_for(method, vendored=vendored)
            if preference_index is not None
            else None
        )

        for objective in objectives:
            _evaluate(objective, cls, method, code, name_hits[objective.id],
                      class_hits[objective.id], findings[objective.id], dex.name,
                      max_targets, vendored, ui_name, pref_evidence)

    return inspected


def _evaluate(
    objective: Objective,
    cls: ClassInfo,
    method: MethodInfo,
    code: MethodCode,
    name_hits: Sequence[str],
    class_hits: Sequence[str],
    finding: ObjectiveFinding,
    dex_name: str,
    max_targets: int,
    vendored: bool = False,
    ui_name: bool = False,
    pref_evidence: Optional[PreferenceEvidence] = None,
) -> None:
    score = 0
    reasons: List[str] = []
    strings: List[str] = []
    calls = code.called_methods
    calls_lower = [call.lower() for call in calls]

    # Constructors are never a safe patch target.
    if method.name in ("<init>", "<clinit>"):
        return

    # A goal such as "allow screenshots" must be solved in the app's own code.
    if vendored and not objective.allow_vendored:
        return

    if (
        objective.excluded_vendor_packages
        and cls.java_name.startswith(objective.excluded_vendor_packages)
    ):
        return

    # Only methods we can safely rewrite are useful. Morphe's returnEarly has
    # overloads for primitives, void and String; an arbitrary object or an array
    # would need hand-written register management.
    return_type = method.return_type
    if return_type.startswith("[") or (
        return_type.startswith("L") and return_type != "Ljava/lang/String;"
    ):
        return

    # 1. Method name signal -----------------------------------------------------
    library_call = False
    if name_hits:
        score += min(8, 4 * len(name_hits))
        reasons.append("method name matches " + ", ".join(f"'{h}'" for h in name_hits[:3]))

    # 2. Class name signal (corroboration only) ---------------------------------
    if class_hits:
        score += 1

    # 3. Text anchors in the method body ---------------------------------------
    text_hits = 0
    for keyword in objective.string_keywords:
        for text in code.strings:
            if keyword.lower() in text.lower():
                score += 2 if text_hits == 0 else 1
                text_hits += 1
                if text not in strings:
                    strings.append(text)
                reasons.append(f"contains the text '{text[:60]}'")
                break
    score += min(2, max(0, text_hits - 2))

    # 3b. Preference-key evidence (the part that survives R8/ProGuard) ----------
    pref_hit = False
    pref_method_hit = False
    pref_keys: List[str] = []
    if objective.trace_preference_keys and pref_evidence is not None:
        pref_hit = True
        pref_method_hit = pref_evidence.source == "method"
        pref_keys = list(pref_evidence.keys)
        score += 6 if pref_evidence.source == "method" else 5
        reasons.append(pref_evidence.detail)
        if pref_evidence.source == "method":
            # These keys are real constants of *this* method, so they are also
            # valid fingerprint anchors. Class-level keys are not copied here.
            for key in pref_keys[:2]:
                if key not in strings:
                    strings.append(key)

    # 4. Calls into known SDKs --------------------------------------------------
    for marker in objective.library_markers:
        for call in calls:
            if marker in call:
                score += 3
                library_call = True
                reasons.append(f"calls the {marker.replace('/', '.')} SDK")
                break

    # 5. Return type suitability ------------------------------------------------
    if method.return_type in objective.acceptable_returns:
        score += 1
    else:
        score -= 3

    # 6. A parameterless boolean check is the easiest, most stable hook --------
    if method.return_type == "Z" and not method.parameters:
        score += 2

    # 7. Obfuscation penalty ----------------------------------------------------
    if looks_like_obfuscated(method.name) and looks_like_obfuscated(cls.java_name.rsplit(".", 1)[-1]):
        score -= 2

    # 8. Third-party/vendored code demotion ------------------------------------
    if vendored:
        score -= 3

    # 8. Literal + call patterns (FLAG_SECURE and friends) ----------------------
    literal_hit = False
    if objective.literal_targets:
        wanted = set(objective.literal_targets)
        hit_literals = sorted({value for value in code.int_constants if value in wanted})
        if hit_literals:
            markers = [m.lower() for m in objective.literal_call_markers]
            if not markers or any(marker in call for call in calls_lower for marker in markers):
                score += 8
                literal_hit = True
                reasons.append(
                    "uses the blocking flag "
                    + ", ".join(f"0x{value:x}" for value in hit_literals)
                )

    # 9. Display-helper names ---------------------------------------------------
    # ``getHasSubscriptionUpgradeHint`` is the label of an upsell banner, not the
    # entitlement check; patching it makes the banner disappear, not premium
    # unlock. A real SDK call or blocking literal overrides this doubt.
    if objective.penalise_ui_names and ui_name and not literal_hit and not library_call:
        score -= 3
        reasons.append("name looks like a display helper, not the feature check")

    # 10. Generic plumbing ------------------------------------------------------
    # ``equals``/``hashCode``/``accept`` touching an SDK is not a feature check.
    # Only matters when the goal already demands real context: for analytics, an
    # ``onClick`` that logs an event is a valid target.
    if (
        objective.penalise_ui_names
        and method.name in _GENERIC_METHOD_NAMES
        and not (name_hits or literal_hit or pref_method_hit)
    ):
        return

    # Inside a billing/ads/analytics SDK, "calls that SDK" proves nothing.
    primary_library = library_call and not vendored
    if objective.require_primary and not (name_hits or literal_hit or primary_library or pref_hit):
        return

    if objective.require_context and not (
        class_hits or text_hits or library_call or literal_hit or pref_hit
    ):
        return

    if score < objective.min_score:
        return

    # Fingerprint anchors: the matched text first, then the longest distinct
    # strings of the method (they are the least likely to change between versions).
    anchors = list(strings)
    for text in sorted(code.strings, key=len, reverse=True):
        if len(anchors) >= 4:
            break
        cleaned = text.strip()
        if 4 <= len(cleaned) <= 80 and cleaned not in anchors and "\n" not in cleaned:
            anchors.append(cleaned)

    candidate = TargetCandidate(
        objective_id=objective.id,
        class_name=cls.java_name,
        class_descriptor=cls.descriptor,
        method_name=method.name,
        method_descriptor=method.descriptor,
        return_type=method.return_type,
        access_flags=method.access_flags,
        score=score,
        strategy=STRATEGY_DROP_FLAG if literal_hit else choose_strategy(
            objective, method.return_type, method.name
        ),
        strings=anchors[:4],
        calls=calls[:8],
        opcodes=code.opcode_names(12),
        literals=sorted({v for v in code.int_constants if v in set(objective.literal_targets)}),
        literal_sites=[
            site for site in code.literal_sites if site[2] in set(objective.literal_targets)
        ][:4],
        reasons=_dedupe(reasons)[:4],
        dex_file=dex_name,
        preference_keys=pref_keys,
        preference_source=pref_evidence.source if pref_hit and pref_evidence else "",
    )

    finding.candidates.append(candidate)
    if len(finding.candidates) > max_targets * 4:
        finding.candidates.sort(key=_rank)
        del finding.candidates[max_targets:]


def _rank(candidate: TargetCandidate):
    return (-candidate.score, len(candidate.class_name), candidate.method_name)


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    unique: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _finalise(report: AnalysisReport, objectives: Sequence[Objective]) -> None:
    for objective in objectives:
        finding = report.findings[objective.id]
        finding.candidates.sort(key=_rank)

        # Keep at most two candidates per class: three sibling methods of the
        # same class are rarely three different decisions.
        per_class: Dict[str, int] = {}
        trimmed: List[TargetCandidate] = []
        for candidate in finding.candidates:
            count = per_class.get(candidate.class_name, 0)
            if count >= 2:
                continue
            per_class[candidate.class_name] = count + 1
            trimmed.append(candidate)
            if len(trimmed) >= MAX_TARGETS_PER_OBJECTIVE:
                break
        finding.candidates = trimmed

        if finding.candidates or finding.detected_libraries:
            finding.present = True

        if finding.candidates:
            scores = [c.score for c in finding.candidates]
            finding.signals.append(f"highest confidence: {max(scores)}")
        elif finding.detected_libraries:
            finding.signals.append(
                "the SDK is bundled but its calls may be hidden behind a wrapper"
            )

    if report.info.packers:
        report.warnings.append(
            "This app is protected with "
            + ", ".join(report.info.packers)
            + ". The code is partly encrypted, so some targets may be invisible."
        )

    if report.obfuscation_ratio > 0.6:
        report.warnings.append(
            "Most class names are obfuscated (R8/ProGuard). Morphy relies on text "
            "and code patterns instead of names, but double-check the suggested targets."
        )

    if report.info.min_sdk and not report.info.min_sdk.isdigit():
        pass

    if not report.has_actionable_targets:
        report.warnings.append(
            "No usable hook was found. Try another objective, or use the custom "
            "search with a word you saw in the app (a message or a feature name)."
        )


def explain(report: AnalysisReport) -> str:
    """Human-readable, jargon-free summary used by the CLI."""
    lines: List[str] = []
    info = report.info
    lines.append(f"App: {info.package or 'unknown'}  (version {info.version_name or '?'})")
    if info.min_sdk:
        lines.append(f"Android {info.min_sdk}+ required by the app")
    lines.append(
        f"Scanned {report.method_count} methods in {report.class_count} classes "
        f"({report.duration_seconds:.1f}s)"
    )

    for finding in report.findings.values():
        lines.append("")
        lines.append(f"[{finding.title}]  {finding.summary()}")
        for candidate in finding.candidates[:3]:
            lines.append(f"  - {candidate.signature}")
            for reason in candidate.reasons:
                lines.append(f"      why: {reason}")

    if report.warnings:
        lines.append("")
        for warning in report.warnings:
            lines.append(f"! {warning}")

    return "\n".join(lines)
