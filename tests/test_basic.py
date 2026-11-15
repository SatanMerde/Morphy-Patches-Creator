"""Unit tests for the real analysis / generation pipeline.

These tests do not need an APK or a JDK: they exercise the pieces that turn
findings into Kotlin, and the checks that keep invalid Morphe code from being
shipped.
"""
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from morphy_creator.core import analysis
from morphy_creator.core.analysis import (
    AnalysisReport,
    ObjectiveFinding,
    TargetCandidate,
    _joined_index,
    _match_any,
    _sdk_packages,
    _tokens,
)
from morphy_creator.core.apk import ApkInfo
from morphy_creator.core.dex import descriptor_to_java, looks_like_obfuscated
from morphy_creator.core.fingerprint import check_candidate, check_report
from morphy_creator.core.preferences import (
    PreferenceEvidence,
    PreferenceIndex,
    looks_like_preference_key,
)
from morphy_creator.core.plan import (
    PatchPlan,
    PatchStep,
    confidence_of,
    dedupe_plans,
    kotlin_class_name,
    plan_for_finding,
    snake_case,
)
from morphy_creator.core.split_merger import SplitApkMerger
from morphy_creator.core.verifier import PatchVerifier
from morphy_creator.core.xrefs import CallGraph, MethodRef
from morphy_creator.presets.objectives import (
    OBJECTIVES_BY_ID,
    STRATEGY_BOOLEAN_FALSE,
    STRATEGY_BOOLEAN_TRUE,
    STRATEGY_DROP_FLAG,
    STRATEGY_RETURN_VOID,
    STRATEGY_RETURN_ZERO,
    choose_strategy,
    custom_objective,
    match_text,
)
from morphy_creator.synthesizer import kotlin
from morphy_creator.synthesizer.patch_writer import PatchWriter, _gradle_error_tail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_candidate(**overrides) -> TargetCandidate:
    data = dict(
        objective_id="premium",
        class_name="com.example.billing.BillingManager",
        class_descriptor="Lcom/example/billing/BillingManager;",
        method_name="isPremiumUser",
        method_descriptor="()Z",
        return_type="Z",
        access_flags=0x0001,
        score=9,
        strategy=STRATEGY_BOOLEAN_TRUE,
        strings=["INAPP_PURCHASE_ITEM_LIST"],
        calls=[],
        opcodes=["const/4", "return"],
        literals=[],
        literal_sites=[],
        reasons=["method name matches 'ispremium'"],
        dex_file="classes.dex",
    )
    data.update(overrides)
    return TargetCandidate(**data)


def make_plan(steps, **overrides) -> PatchPlan:
    data = dict(
        package_name="premium",
        app_package="com.example",
        app_version="1.0",
        objective_id="premium",
        title="Unlock premium / paid features",
        description="Bypass in-app purchase checks.",
        class_name="UnlockPremiumPaidFeaturesPatch",
        steps=list(steps),
        confidence="high",
        notes=[],
    )
    data.update(overrides)
    return PatchPlan(**data)


def make_report(findings) -> AnalysisReport:
    info = ApkInfo(path=Path("example.apk"), package="com.example", version_name="1.0")
    return AnalysisReport(
        info=info,
        findings={finding.objective_id: finding for finding in findings},
        method_count=100,
        class_count=10,
    )


def fake_code(**overrides) -> SimpleNamespace:
    data = dict(
        called_methods=[],
        strings=[],
        int_constants=[],
        literal_sites=[],
        opcode_names=lambda _limit: ["return"],
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def fake_method(**overrides) -> SimpleNamespace:
    data = dict(
        name="isPremiumUser",
        descriptor="()Z",
        return_type="Z",
        parameters=(),
        access_flags=0x0001,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def fake_class(**overrides) -> SimpleNamespace:
    data = dict(
        java_name="com.example.billing.BillingManager",
        descriptor="Lcom/example/billing/BillingManager;",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def evaluate(objective_id, method, code=None, name_hits=(), class_hits=(), ui_name=False,
             cls=None, vendored=False, pref_evidence=None):
    objective = OBJECTIVES_BY_ID[objective_id]
    finding = ObjectiveFinding(objective_id=objective.id, title=objective.title)
    analysis._evaluate(
        objective,
        cls or fake_class(),
        method,
        code or fake_code(),
        list(name_hits),
        list(class_hits),
        finding,
        "classes.dex",
        6,
        vendored,
        ui_name,
        pref_evidence,
    )
    return finding.candidates


class FakeDexMethod:
    """Duck-typed MethodInfo for the call-graph / preference / fingerprint tests."""

    def __init__(self, class_descriptor, name, descriptor, return_type,
                 parameters=(), strings=(), calls=(), fields=(), access_flags=0x0001):
        self.class_descriptor = class_descriptor
        self.name = name
        self.descriptor = descriptor
        self.return_type = return_type
        self.parameters = tuple(parameters)
        self.access_flags = access_flags
        self.has_body = True
        self._code = SimpleNamespace(
            strings=list(strings),
            called_methods=list(calls),
            field_accesses=list(fields),
            complete=True,
        )

    @property
    def full_name(self) -> str:
        return f"{self.class_descriptor}->{self.name}{self.descriptor}"

    def code(self):
        return self._code

    def uses_strings(self):
        return list(self._code.strings)


def fake_dex(methods):
    return SimpleNamespace(iter_methods=lambda: iter(methods))


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------
def test_verifier_rejects_revanced_api():
    legacy = (
        'package app.morphe.patches.test\n'
        'import app.morphe.patcher.annotation.Patch\n'
        '@Patch(name = "Test")\n'
        'object TestPatch : BytecodePatch() {\n'
        '    object Fp : Fingerprint(strings = listOf("foo"))\n'
        '    override fun execute() { Fp.result?.method?.replaceMethod() }\n'
        '}\n'
    )
    result = PatchVerifier.verify_source(legacy, "Legacy.kt")
    assert result.valid is False
    joined = " ".join(result.errors)
    assert "@Patch" in joined
    assert "replaceMethod" in joined


def test_verifier_rejects_unbalanced_source():
    result = PatchVerifier.verify_source("package a\nval x = patch( {\n", "Broken.kt")
    assert result.valid is False
    assert any("Unbalanced" in error for error in result.errors)


def test_verifier_reports_weak_fingerprint():
    source = (
        "package app.morphe.patches.test\n"
        "import app.morphe.patcher.Fingerprint\n"
        "import app.morphe.patcher.match\n"
        "import app.morphe.patcher.util.returnEarly\n"
        "val testPatch = patch(name = \"Test\") {\n"
        "    execute { Fp.match().method.returnEarly(false) }\n"
        "}\n"
        "private object Fp : Fingerprint(\n"
        "    strings = listOf(\"true\"),\n"
        ")\n"
    )
    result = PatchVerifier.verify_source(source, "Weak.kt")
    assert any("single signal" in warning for warning in result.warnings)
    assert any("generic text" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Kotlin renderer
# ---------------------------------------------------------------------------
def test_kotlin_render_uses_current_morphe_api():
    plan = make_plan([PatchStep(target=make_candidate(), strategy=STRATEGY_BOOLEAN_TRUE)])
    source = kotlin.render(plan)

    assert "package app.morphe.patches.premium" in source
    assert "val unlockPremiumPaidFeaturesPatch = patch(" in source
    assert "@Patch" not in source
    assert "replaceMethod" not in source
    assert "import app.morphe.patcher.match" in source
    assert "returnEarly(true)" in source
    assert "Fingerprint(" in source
    assert 'definingClass = "Lcom/example/billing/BillingManager;"' in source
    assert 'name = "isPremiumUser"' in source
    assert 'compatibleWith(Compatibility("com.example", "example"))' in source


def test_kotlin_render_boolean_false_and_void():
    false_plan = make_plan(
        [PatchStep(target=make_candidate(strategy=STRATEGY_BOOLEAN_FALSE), strategy=STRATEGY_BOOLEAN_FALSE)],
        objective_id="ads",
        package_name="ads",
        title="Remove ads",
        class_name="RemoveAdsPatch",
    )
    false_source = kotlin.render(false_plan)
    assert "returnEarly(false)" in false_source

    void_step = PatchStep(
        target=make_candidate(
            objective_id="tracking",
            method_name="logEvent",
            method_descriptor="(Ljava/lang/String;)V",
            return_type="V",
            strategy=STRATEGY_RETURN_VOID,
        ),
        strategy=STRATEGY_RETURN_VOID,
    )
    void_plan = make_plan(
        [void_step],
        objective_id="tracking",
        package_name="tracking",
        title="Disable analytics and tracking",
        class_name="DisableAnalyticsAndTrackingPatch",
    )
    void_source = kotlin.render(void_plan)
    assert "returnEarly()" in void_source
    assert 'parameters = listOf("Ljava/lang/String;")' in void_source


def test_kotlin_drop_flag_replaces_instruction():
    candidate = make_candidate(
        objective_id="screenshots",
        class_name="com.example.BaseActivity",
        class_descriptor="Lcom/example/BaseActivity;",
        method_name="onResume",
        method_descriptor="()V",
        return_type="V",
        strategy=STRATEGY_DROP_FLAG,
        strings=[],
        literals=[0x2000],
        literal_sites=[(0x13, 4, 0x2000)],
    )
    plan = make_plan(
        [PatchStep(target=candidate, strategy=STRATEGY_DROP_FLAG)],
        objective_id="screenshots",
        package_name="screenshots",
        title="Allow screenshots",
        class_name="AllowScreenshotsPatch",
    )
    source = kotlin.render(plan)
    assert "import app.morphe.patcher.literal" in source
    assert "import app.morphe.patcher.instructionMatches" in source
    assert "filters = listOf(literal(8192))" in source
    assert "replaceInstruction(" in source
    assert 'const/16 v4, 0x0' in source
    assert "returnEarly" not in source


def test_kotlin_string_return_uses_empty_string():
    candidate = make_candidate(
        method_name="getEntitlementLabel",
        return_type="Ljava/lang/String;",
        method_descriptor="()Ljava/lang/String;",
        strategy=STRATEGY_RETURN_ZERO,
    )
    plan = make_plan([PatchStep(target=candidate, strategy=STRATEGY_RETURN_ZERO)])
    source = kotlin.render(plan)
    assert 'returnEarly("")' in source


def test_kotlin_fingerprint_names_are_valid_identifiers():
    synthetic = make_candidate(method_name="access$getHasSubscriptionUpgradeHint")
    normal = make_candidate(method_name="getHasSubscriptionUpgradeHint")
    source = kotlin.render(make_plan([
        PatchStep(target=synthetic, strategy=STRATEGY_BOOLEAN_TRUE),
        PatchStep(target=normal, strategy=STRATEGY_BOOLEAN_TRUE),
    ]))
    assert "object accessGetHasSubscriptionUpgradeHintFingerprint" in source
    assert "$Fingerprint" not in source


def test_kotlin_fingerprint_names_avoid_collisions():
    overload_a = make_candidate(method_descriptor="()Z")
    overload_b = make_candidate(method_descriptor="(I)Z")
    source = kotlin.render(make_plan([
        PatchStep(target=overload_a, strategy=STRATEGY_BOOLEAN_TRUE),
        PatchStep(target=overload_b, strategy=STRATEGY_BOOLEAN_TRUE),
    ]))
    assert "isPremiumUserFingerprint" in source
    assert "isPremiumUser2Fingerprint" in source


def test_kotlin_escapes_dangerous_text():
    candidate = make_candidate(strings=['He said "hi" $var \\ end'])
    source = kotlin.render(make_plan([PatchStep(target=candidate, strategy=STRATEGY_BOOLEAN_TRUE)]))
    assert '\\"hi\\"' in source
    assert "\\$var" in source


def test_kotlin_obfuscated_target_gets_call_filter_and_version_pin():
    candidate = make_candidate(
        class_name="az4",
        class_descriptor="Laz4;",
        method_name="a",
        method_descriptor="()Z",
        strings=[],
        calls=["Lrd5;->e(Ltg2;Ljava/lang/Object;)Ljava/lang/Boolean;"],
    )
    plan = make_plan(
        [PatchStep(target=candidate, strategy=STRATEGY_BOOLEAN_TRUE)],
        app_package="com.michaldrabik.showly2",
        app_version="3.72.0",
    )
    source = kotlin.render(plan)

    assert "import app.morphe.patcher.methodCall" in source
    assert "methodCall(" in source
    assert 'definingClass = "Lrd5;"' in source
    assert 'name = "e"' in source
    assert 'AppTarget(version = "3.72.0")' in source
    assert "import app.morphe.patcher.patch.AppTarget" in source
    assert PatchVerifier.verify_source(source).valid is True


def test_generated_patch_passes_verifier():
    plan = make_plan([PatchStep(target=make_candidate(), strategy=STRATEGY_BOOLEAN_TRUE)])
    result = PatchVerifier.verify_source(kotlin.render(plan), "Generated.kt")
    assert result.valid is True
    assert result.score >= 90


# ---------------------------------------------------------------------------
# Plan model
# ---------------------------------------------------------------------------
def test_naming_helpers():
    assert kotlin_class_name("Remove ads") == "RemoveAdsPatch"
    assert kotlin_class_name("123 weirds") == "Patch123WeirdsPatch"
    assert snake_case("Unlock premium / paid features") == "unlock_premium_paid_features"
    assert confidence_of(9) == "high"
    assert confidence_of(7) == "medium"
    assert confidence_of(4) == "low"


def test_plan_for_finding_builds_steps_and_notes():
    objective = OBJECTIVES_BY_ID["premium"]
    finding = ObjectiveFinding(
        objective_id="premium",
        title=objective.title,
        candidates=[make_candidate(score=9), make_candidate(method_name="isPro", score=7)],
        present=True,
    )
    report = make_report([finding])
    plan = plan_for_finding(report, finding, objective, max_steps=1)

    assert len(plan.steps) == 1
    assert plan.confidence == "high"
    assert plan.class_name.endswith("Patch")
    assert plan.plain_summary()
    assert plan.verify_hint == objective.verify_hint
    assert plan.limits == objective.limits

    empty = plan_for_finding(report, ObjectiveFinding("premium", "Premium"), objective)
    assert empty.is_empty
    assert empty.notes


def test_dedupe_plans_removes_duplicate_targets():
    shared = make_candidate()
    first = make_plan([PatchStep(target=shared, strategy=STRATEGY_BOOLEAN_TRUE)])
    second = make_plan(
        [PatchStep(target=shared, strategy=STRATEGY_BOOLEAN_TRUE)],
        objective_id="custom",
        title="Custom search",
    )
    unique = dedupe_plans([first, second])
    assert len(unique) == 1


def test_plans_for_report_skips_absent_objectives():
    from morphy_creator.core.plan import plans_for_report

    objective = OBJECTIVES_BY_ID["root"]
    report = make_report([ObjectiveFinding("root", "Bypass root detection")])
    plans = plans_for_report(report, [objective])
    assert len(plans) == 1
    assert plans[0].is_empty


# ---------------------------------------------------------------------------
# Objectives
# ---------------------------------------------------------------------------
def test_match_text_understands_plain_french_and_english():
    ids = {objective.id for objective in match_text("enlever les pubs et autoriser les captures")}
    assert "ads" in ids
    assert "screenshots" in ids

    ids = {objective.id for objective in match_text("unlock premium and block updates")}
    assert {"premium", "updates"} <= ids


def test_choose_strategy_follows_return_type():
    premium = OBJECTIVES_BY_ID["premium"]
    assert choose_strategy(premium, "Z") in (STRATEGY_BOOLEAN_TRUE, STRATEGY_BOOLEAN_FALSE)
    assert choose_strategy(premium, "I") == "return_zero"

    tracking = OBJECTIVES_BY_ID["tracking"]
    assert choose_strategy(tracking, "V") == STRATEGY_RETURN_VOID


def test_choose_strategy_respects_name_polarity():
    premium = OBJECTIVES_BY_ID["premium"]
    ads = OBJECTIVES_BY_ID["ads"]

    assert choose_strategy(premium, "Z", "hasPaidLicense") == STRATEGY_BOOLEAN_TRUE
    assert choose_strategy(premium, "Z", "isTrialExpired") == STRATEGY_BOOLEAN_FALSE
    assert choose_strategy(premium, "Z", "isNotPremium") == STRATEGY_BOOLEAN_FALSE
    assert choose_strategy(ads, "Z", "shouldShowAd") == STRATEGY_BOOLEAN_FALSE
    assert choose_strategy(ads, "Z", "hasNoAds") == STRATEGY_BOOLEAN_TRUE


def test_custom_objective_is_permissive():
    objective = custom_objective(["my", "My", " feature "])
    assert objective.id == "custom"
    assert objective.method_keywords == ("feature", "my")
    assert objective.require_primary is False


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------
def test_token_matching_avoids_false_positives():
    assert _tokens("isAdEnabled") == ["is", "ad", "enabled"]
    import_index = _joined_index(_tokens("isAdded"))
    ad_index = _joined_index(_tokens("isAdEnabled"))
    assert _match_any(["isad"], import_index) == []
    assert _match_any(["isad"], ad_index) == ["isad"]


def test_descriptor_helpers():
    assert descriptor_to_java("Lcom/foo/Bar;") == "com.foo.Bar"
    assert descriptor_to_java("[Ljava/lang/String;") == "java.lang.String[]"
    assert looks_like_obfuscated("ad") is True
    assert looks_like_obfuscated("isPremiumUser") is False


def test_sdk_packages_are_dotted_prefixes():
    objective = OBJECTIVES_BY_ID["premium"]
    packages = _sdk_packages([objective])
    assert "com.android.billingclient." in packages
    assert all(package.endswith(".") for package in packages)


def test_analysis_keeps_a_real_premium_check():
    method = fake_method(name="isPremiumUser", parameters=())
    cls = fake_class(java_name="com.example.billing.BillingManager")
    candidates = evaluate(
        "premium", method, name_hits=["ispremium"], class_hits=["billing"], cls=cls,
    )
    assert candidates
    assert candidates[0].strategy in (STRATEGY_BOOLEAN_TRUE, STRATEGY_BOOLEAN_FALSE)
    assert candidates[0].score >= 6


def test_analysis_drops_display_helpers_for_boolean_goals():
    """``getHasSubscriptionUpgradeHint`` labels a banner, it does not gate premium."""
    method = fake_method(
        name="getHasSubscriptionUpgradeHint",
        descriptor="(Lcom/example/LicenseState;)Z",
        parameters=("Lcom/example/LicenseState;",),
    )
    cls = fake_class(java_name="com.example.LicenseBinder")
    candidates = evaluate(
        "premium", method, name_hits=["hassubscription"], class_hits=["license"],
        ui_name=True, cls=cls,
    )
    assert candidates == []


def test_analysis_ignores_generic_sdk_calls():
    """An app ``equals()`` that happens to call an SDK is not a premium gate."""
    method = fake_method(name="equals", descriptor="(Ljava/lang/Object;)Z",
                         parameters=("Ljava/lang/Object;",))
    code = fake_code(
        called_methods=["Lcom/qonversion/android/sdk/dto/purchase/Inapp;->hashCode()I"],
    )
    assert evaluate("premium", method, code=code) == []


def test_analysis_drops_sdk_internal_library_only_hits():
    """Inside the billing SDK, 'calls the billing SDK' proves nothing."""
    method = fake_method(name="consumePurchases", descriptor="()V", return_type="V")
    code = fake_code(
        called_methods=["Lcom/android/billingclient/api/BillingClient;->queryPurchases(Ljava/lang/String;)Lcom/android/billingclient/api/PurchaseResult;"],
    )
    cls = fake_class(java_name="com.qonversion.android.sdk.internal.billing.QonversionBillingService")
    assert evaluate("premium", method, code=code, cls=cls, vendored=True) == []


def test_analysis_keeps_named_hook_inside_an_sdk():
    """A method that *is* an entitlement check is useful wherever it lives."""
    method = fake_method(name="isPremiumUser", return_type="Z")
    cls = fake_class(java_name="com.example.sdk.Entitlements")
    candidates = evaluate(
        "premium", method, name_hits=["ispremium"],
        class_hits=["entitlement"], cls=cls,
    )
    assert candidates
    assert candidates[0].method_name == "isPremiumUser"


# ---------------------------------------------------------------------------
# Call graph
# ---------------------------------------------------------------------------
def test_method_ref_parse_roundtrip():
    ref = MethodRef.parse("Lcom/foo/Bar;->a(Ljava/lang/String;I)Z")
    assert ref.class_descriptor == "Lcom/foo/Bar;"
    assert ref.name == "a"
    assert ref.descriptor == "(Ljava/lang/String;I)Z"
    assert ref.full_name == "Lcom/foo/Bar;->a(Ljava/lang/String;I)Z"
    assert ref.signature == "a(Ljava/lang/String;I)Z"


def test_call_graph_indexes_only_apk_methods():
    caller = FakeDexMethod(
        "Lcom/example/MainActivity;", "onResume", "()V", "V",
        calls=["Laz4;->a()Z", "Landroid/app/Activity;->onResume()V"],
    )
    premium = FakeDexMethod("Laz4;", "a", "()Z", "Z")
    graph = CallGraph.build([fake_dex([caller, premium])])

    assert graph.method_count == 2
    assert graph.callers("Laz4;->a()Z") == ["Lcom/example/MainActivity;->onResume()V"]
    assert graph.callees("Lcom/example/MainActivity;->onResume()V")[0] == "Laz4;->a()Z"
    assert graph.is_declared("Laz4;->a()Z") is True
    assert graph.find("a()") == ["Laz4;->a()Z"]


def test_call_graph_does_not_group_obfuscated_names():
    caller_x = FakeDexMethod("Lx;", "m", "()V", "V", calls=["Lx;->a()Z"])
    caller_y = FakeDexMethod("Ly;", "n", "()V", "V", calls=["Ly;->a()Z"])
    method_x = FakeDexMethod("Lx;", "a", "()Z", "Z")
    method_y = FakeDexMethod("Ly;", "a", "()Z", "Z")
    graph = CallGraph.build([fake_dex([caller_x, caller_y, method_x, method_y])])

    assert graph.callers("Lx;->a()Z", include_overrides=False) == ["Lx;->m()V"]
    assert graph.callers("Lx;->a()Z", include_overrides=True) == ["Lx;->m()V"]
    assert graph.implementations("Lx;->a()Z") == []

    named_x = FakeDexMethod("Lx;", "isPremium", "()Z", "Z")
    named_y = FakeDexMethod("Ly;", "isPremium", "()Z", "Z")
    named_caller = FakeDexMethod("Lz;", "check", "()V", "V", calls=["Ly;->isPremium()Z"])
    graph = CallGraph.build([fake_dex([named_x, named_y, named_caller])])
    assert graph.callers("Lx;->isPremium()Z", include_overrides=True) == ["Lz;->check()V"]
    assert set(graph.implementations("Lx;->isPremium()Z")) == {"Lx;->isPremium()Z", "Ly;->isPremium()Z"}


# ---------------------------------------------------------------------------
# Preference tracing
# ---------------------------------------------------------------------------
def test_preference_key_shapes():
    for key in (
        "KEY_PREMIUM", "KEY_PREMIUM_UNLOCKED", "is_premium", "premiumUser",
        "subscription_active", "is_purchased", "LICENCE_VALID", "trialExpired",
    ):
        assert looks_like_preference_key(key) is True, key

    for key in (
        "Premium", "subscription", "ecommerce_purchase", "in_app_purchase",
        "purchase_token", "app_store_subscription_cancel",
        "subscription_started", "android.intent.action.USER_UNLOCKED",
        "com.android.vending.billing.PURCHASES_UPDATED",
        "https://example.com/premium",
    ):
        assert looks_like_preference_key(key) is False, key


def test_preference_index_finds_delegate_holder():
    ctor = FakeDexMethod(
        "Laz4;", "<init>", "(Landroid/content/SharedPreferences;)V", "V",
        strings=["KEY_PREMIUM"],
        calls=["Lrd5;-><init>(Landroid/content/SharedPreferences;Ljava/lang/String;Z)V"],
    )
    getter = FakeDexMethod(
        "Laz4;", "a", "()Z", "Z",
        calls=["Lrd5;->e(Ltg2;Ljava/lang/Object;)Ljava/lang/Boolean;"],
    )
    event_holder = FakeDexMethod(
        "Lpv1;", "x", "()J", "J", strings=["app_store_subscription_cancel"],
    )
    index = PreferenceIndex.build([fake_dex([ctor, getter, event_holder])])

    evidence = index.evidence_for(getter)
    assert evidence is not None
    assert evidence.source == "class"
    assert evidence.keys == ("KEY_PREMIUM",)
    assert any("SharedPreferences" in key for key in evidence.keys) is False
    assert index.evidence_for(event_holder) is None
    assert index.candidate_getters()[0]["method"] == "Laz4;->a()Z"


def test_preference_index_method_level_key():
    reader = FakeDexMethod(
        "Lcom/example/Settings;", "isPremium", "()Z", "Z",
        strings=["is_premium"],
        calls=["Landroid/content/SharedPreferences;->getBoolean(Ljava/lang/String;Z)Z"],
    )
    index = PreferenceIndex.build([fake_dex([reader])])
    evidence = index.evidence_for(reader)
    assert evidence is not None
    assert evidence.source == "method"
    assert evidence.keys == ("is_premium",)

    with_parameter = FakeDexMethod(
        "Lcom/example/Settings;", "check", "(Ljava/lang/String;)Z", "Z",
        parameters=("Ljava/lang/String;",),
        strings=["is_premium"],
    )
    assert index.evidence_for(with_parameter) is None


def test_analysis_uses_preference_evidence_for_obfuscated_getter():
    evidence = PreferenceEvidence(
        ("KEY_PREMIUM",), "class",
        "the class stores 'KEY_PREMIUM' in SharedPreferences",
    )
    candidates = evaluate(
        "premium",
        fake_method(name="a", descriptor="()Z", return_type="Z", parameters=()),
        cls=fake_class(java_name="az4", descriptor="Laz4;"),
        pref_evidence=evidence,
    )
    assert candidates
    assert candidates[0].preference_keys == ["KEY_PREMIUM"]
    assert candidates[0].strategy == STRATEGY_BOOLEAN_TRUE
    assert any("SharedPreferences" in reason for reason in candidates[0].reasons)


def test_analysis_reads_negative_names_as_false():
    evidence = PreferenceEvidence(("trialExpired",), "method", "reads 'trialExpired'")
    candidates = evaluate(
        "premium", fake_method(name="isTrialExpired"), pref_evidence=evidence,
    )
    assert candidates
    assert candidates[0].strategy == STRATEGY_BOOLEAN_FALSE


# ---------------------------------------------------------------------------
# Fingerprint uniqueness
# ---------------------------------------------------------------------------
def test_fingerprint_unique_ambiguous_missing():
    method = FakeDexMethod(
        "Lcom/example/billing/BillingManager;", "isPremiumUser", "()Z", "Z",
        strings=["INAPP_PURCHASE_ITEM_LIST"],
    )
    unique = check_candidate([fake_dex([method])], make_candidate())
    assert unique.verdict == "unique"
    assert unique.exact_matches == 1

    ambiguous = check_candidate([fake_dex([method, method])], make_candidate())
    assert ambiguous.verdict == "ambiguous"
    assert ambiguous.exact_matches == 2

    missing = check_candidate(
        [fake_dex([method])], make_candidate(strings=["NO_SUCH_STRING"]),
    )
    assert missing.verdict == "missing"


def test_fingerprint_report_drops_missing_candidates():
    finding = ObjectiveFinding(
        objective_id="premium", title="Premium",
        candidates=[make_candidate(strings=["NO_SUCH_STRING"])],
    )
    report = make_report([finding])
    method = FakeDexMethod(
        "Lcom/example/billing/BillingManager;", "isPremiumUser", "()Z", "Z",
        strings=["INAPP_PURCHASE_ITEM_LIST"],
    )
    check_report(report, [fake_dex([method])])
    assert finding.candidates == []
    assert any("discarded" in warning for warning in report.warnings)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------
def test_patch_writer_writes_into_package_folder():
    with tempfile.TemporaryDirectory() as tmp_dir:
        writer = PatchWriter(Path(tmp_dir))
        plan = make_plan([PatchStep(target=make_candidate(), strategy=STRATEGY_BOOLEAN_TRUE)])
        path = writer.write(plan)

        assert path.exists()
        assert path.name == "UnlockPremiumPaidFeaturesPatch.kt"
        assert path.parent.as_posix().endswith("src/app/morphe/patches/premium")
        assert "patch(" in path.read_text(encoding="utf-8")


def test_build_bundle_without_sources_is_honest():
    with tempfile.TemporaryDirectory() as tmp_dir:
        writer = PatchWriter(Path(tmp_dir))
        result = writer.build_bundle([])
        assert result.is_bundle is False
        assert result.kind == "project"
        assert result.next_steps


def test_run_gradle_launches_windows_wrapper():
    """Regression guard for the [WinError 2] .bat launch failure."""
    if sys.platform != "win32":
        return
    from morphy_creator.synthesizer.patch_writer import _run_gradle

    with tempfile.TemporaryDirectory() as tmp_dir:
        project = Path(tmp_dir)
        (project / "gradlew.bat").write_text("@echo off\r\nexit /b 0\r\n", encoding="ascii")
        ok, message = _run_gradle(project)
        assert ok is True, message
        assert message == ""


def test_run_gradle_reports_failure_output():
    if sys.platform != "win32":
        return
    from morphy_creator.synthesizer.patch_writer import _run_gradle

    with tempfile.TemporaryDirectory() as tmp_dir:
        project = Path(tmp_dir)
        (project / "gradlew.bat").write_text(
            "@echo off\r\necho e: unresolved reference: missing\r\nexit /b 1\r\n",
            encoding="ascii",
        )
        ok, message = _run_gradle(project)
        assert ok is False
        assert "unresolved reference" in message


def test_gradle_error_tail_keeps_actionable_lines():
    stdout = (
        "> Task :patches:compileKotlin\n"
        "Downloading https://example.invalid\n"
        "e: file.kt:12:1 unresolved reference: foo\n"
        "FAILURE: Build failed with an exception.\n"
    )
    tail = _gradle_error_tail("", stdout)
    assert "unresolved reference: foo" in tail
    assert "FAILURE" in tail
    assert "Downloading" not in tail
    assert "> Task" not in tail


# ---------------------------------------------------------------------------
# Split bundles
# ---------------------------------------------------------------------------
def test_split_merger_extracts_base_apk():
    with tempfile.TemporaryDirectory() as tmp_dir:
        bundle_path = Path(tmp_dir) / "app.apkm"
        with zipfile.ZipFile(bundle_path, "w") as zf:
            zf.writestr("base.apk", b"PK\x03\x04")
            zf.writestr("split_config.fr.apk", b"PK\x03\x04")

        base_apk = SplitApkMerger.extract_and_merge(bundle_path, Path(tmp_dir) / "extracted")
        assert base_apk is not None
        assert base_apk.name == "base.apk"
        assert SplitApkMerger.is_split_bundle(bundle_path) is True


if __name__ == "__main__":
    failures = 0
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            try:
                function()
                print(f"ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("All tests passed." if not failures else f"{failures} test(s) failed.")
    sys.exit(1 if failures else 0)
