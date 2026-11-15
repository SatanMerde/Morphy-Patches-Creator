"""
Plain-English objective catalog.

This is the list a non-technical user picks from. Each objective carries the
technical knowledge that used to live in a developer's head:

* which method names, class names and string constants matter for that goal,
* which libraries indicate the feature is present,
* which code transformation is safe for a given return type,
* what the user should test by hand afterwards.

Nothing here is simulated: the analysis layer only reports candidates that
really exist in the APK's bytecode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

# Transformation strategies understood by the patch template engine.
STRATEGY_BOOLEAN_TRUE = "boolean_true"       # return true
STRATEGY_BOOLEAN_FALSE = "boolean_false"     # return false
STRATEGY_RETURN_VOID = "return_void"         # return (does nothing)
STRATEGY_RETURN_ZERO = "return_zero"         # return 0 / 0L / null-ish
STRATEGY_CLEAR_BODY = "clear_body"           # empty the method
STRATEGY_DROP_FLAG = "drop_flag"             # skip the scary bit-flag

STRATEGY_LABELS: Dict[str, str] = {
    STRATEGY_BOOLEAN_TRUE: "always answer \"yes\"",
    STRATEGY_BOOLEAN_FALSE: "always answer \"no\"",
    STRATEGY_RETURN_VOID: "skip the action",
    STRATEGY_RETURN_ZERO: "return an empty value",
    STRATEGY_CLEAR_BODY: "disable the method body",
    STRATEGY_DROP_FLAG: "remove the blocking flag",
}


@dataclass(frozen=True)
class Objective:
    """One user-facing goal, with the technical profile to detect it."""

    id: str
    title: str
    tagline: str
    explanation: str
    limits: str
    verify_hint: str

    # Detection profiles (case-insensitive substring matches).
    method_keywords: Tuple[str, ...] = ()
    class_keywords: Tuple[str, ...] = ()
    string_keywords: Tuple[str, ...] = ()
    library_markers: Tuple[str, ...] = ()

    # Which change makes sense for which return type.
    strategies: Tuple[str, ...] = (STRATEGY_BOOLEAN_TRUE,)
    acceptable_returns: Tuple[str, ...] = ("Z",)
    min_score: int = 4

    # A candidate must carry a strong signal (name, SDK call, blocking flag).
    # Class-name and text hits alone are only corroboration.
    require_primary: bool = True

    # When true, the class/package or the text of the method must ALSO mention
    # the feature. This kills look-alike names such as FilePathComponents.isRooted
    # in an app that does no root detection at all.
    require_context: bool = False

    # Some goals must never be satisfied by a bundled library (androidx, kotlin,
    # Google Play services). "Allow screenshots" is one: the app's own window
    # code is the target, not RecyclerView internals that happen to use 0x2000.
    allow_vendored: bool = True

    # For "is this true?" goals, a method whose name talks about a hint, banner
    # or dialog is usually a display helper, not the decision. That distinction
    # is meaningless for "hide ads" / "remove watermark", where hiding is the
    # point, so it is opt-in.
    penalise_ui_names: bool = False

    # Only used by strategies that look for a specific integer literal.
    literal_targets: Tuple[int, ...] = ()
    literal_call_markers: Tuple[str, ...] = ()

    tags: Tuple[str, ...] = field(default_factory=tuple)


OBJECTIVES: Tuple[Objective, ...] = (
    Objective(
        id="ads",
        title="Remove ads",
        tagline="Hide banners, interstitials and rewarded videos",
        explanation=(
            "Looks for the methods that decide whether an advert is shown "
            "(showAd, loadAd, isAdLoaded, ...) and the advertising libraries "
            "bundled in the app."
        ),
        limits=(
            "Works when the decision is made inside the app. Ads delivered by a "
            "server that ignores the client (server-side ad stitching, some "
            "video ads) cannot be removed this way."
        ),
        verify_hint="Open the app and browse 3-4 screens: no banner, no pop-up, no video ad.",
        method_keywords=(
            "showad", "loadad", "isad", "adloaded", "advisible", "displayad",
            "showinterstitial", "loadinterstitial", "showrewarded", "isadavailable",
            "adsvisible", "shouldshowad", "getad", "requestad", "adrequest",
            "ispremiumuser", "shouldshowads",
        ),
        class_keywords=("ad", "ads", "advert", "interstitial", "admob", "appodeal"),
        string_keywords=(
            "admob", "applovin", "unityads", "ironsource", "mopub", "adcolony",
            "vungle", "facebook_ads", "audience_network", "mintegral",
        ),
        library_markers=(
            "com/google/android/gms/ads", "com/applovin", "com/unity3d/ads",
            "com/ironsource", "com/mopub", "com/adcolony", "com/vungle",
            "com/facebook/ads", "com/mintegral", "com/chartboost",
        ),
        strategies=(
            STRATEGY_BOOLEAN_FALSE, STRATEGY_BOOLEAN_TRUE,
            STRATEGY_RETURN_VOID, STRATEGY_CLEAR_BODY,
        ),
        acceptable_returns=("Z", "V"),
        min_score=4,
        tags=("monetisation",),
    ),
    Objective(
        id="premium",
        title="Unlock premium / paid features",
        tagline="Bypass in-app purchase and subscription checks",
        explanation=(
            "Finds the local checks such as isPremium, hasSubscription, "
            "isProVersion and makes them answer \"yes\"."
        ),
        limits=(
            "Only local checks can be changed. If the server verifies your "
            "purchase, the paid content stays locked - no client patch can "
            "change that."
        ),
        verify_hint="Restart the app and open the locked feature: it should open without buying.",
        method_keywords=(
            "ispremium", "ispro", "haspremium", "haspro", "issubscribed",
            "hassubscription", "ispaid", "haspaid", "haspaidlicense", "ispurchased",
            "haslicense", "islicensed", "hasvalidlicense", "licensevalid",
            "islicensevalid", "isunlocked", "checkpurchase", "verifypurchase",
            "hasentitlement", "isentitled", "isvip", "hasvip", "isproversion",
            "getpurchasestate", "ispurchasesupported", "isbilling", "checklicense",
            "hastrial", "hasactivetrial", "istrial", "trialactive", "trialexpired",
        ),
        class_keywords=("billing", "purchase", "subscription", "premium", "license", "entitlement"),
        string_keywords=(
            "inapp", "subs", "billing", "purchase_token", "is_premium",
            "premiumuser", "subscription",
        ),
        library_markers=(
            "com/android/billingclient", "com/revenuecat", "com/adapty",
            "com/qonversion", "com/amplitude/experiment",
        ),
        strategies=(STRATEGY_BOOLEAN_TRUE, STRATEGY_RETURN_ZERO),
        acceptable_returns=("Z", "I", "J"),
        min_score=4,
        require_context=True,
        penalise_ui_names=True,
        tags=("monetisation",),
    ),
    Objective(
        id="screenshots",
        title="Allow screenshots",
        tagline="Stop the app from blocking screen capture",
        explanation=(
            "Finds code that adds the FLAG_SECURE window flag (the flag that "
            "makes screenshots come out black) and removes that flag."
        ),
        limits=(
            "Apps that blank the screen with a custom overlay instead of "
            "FLAG_SECURE may still block capture. Banking apps often use "
            "hardware-backed protection."
        ),
        verify_hint="Try a screenshot (or screen recording) on the previously blocked screen.",
        method_keywords=("setflags", "addflags", "setsecure", "enablesecure", "screenshield"),
        class_keywords=("window", "secure", "screen", "screenshot"),
        string_keywords=("FLAG_SECURE",),
        strategies=(STRATEGY_DROP_FLAG,),
        acceptable_returns=("V",),
        min_score=6,
        allow_vendored=False,
        literal_targets=(0x2000,),                 # WindowManager.LayoutParams.FLAG_SECURE
        literal_call_markers=("addFlags", "setFlags"),
        tags=("privacy", "quality-of-life"),
    ),
    Objective(
        id="root",
        title="Bypass root detection",
        tagline="Let the app run on a rooted phone",
        explanation=(
            "Finds the local root checks (isRooted, checkRoot, RootBeer, su "
            "binary lookups) and makes them report \"not rooted\"."
        ),
        limits=(
            "If the app uses hardware attestation (Play Integrity strong verdict) "
            "or a commercial packer, this patch alone is not enough."
        ),
        verify_hint="Open the app on the rooted device: no \"rooted device\" warning.",
        method_keywords=(
            "isrooted", "checkroot", "detectroot", "hasroot", "isdevicerooted",
            "rootbeer", "checksu", "findbinary", "issuperuser", "checkmagisk",
            "detectmagisk", "isrootavailable",
        ),
        class_keywords=("root", "su", "magisk", "superuser"),
        string_keywords=("/su", "superuser.apk", "magisk", "busybox", "which su", "test-keys"),
        strategies=(STRATEGY_BOOLEAN_FALSE, STRATEGY_RETURN_ZERO),
        acceptable_returns=("Z", "I"),
        min_score=4,
        require_context=True,
        penalise_ui_names=True,
        tags=("security",),
    ),
    Objective(
        id="emulator",
        title="Bypass emulator detection",
        tagline="Let the app run inside an emulator or on a PC",
        explanation=(
            "Finds local emulator checks (isEmulator, goldfish, genymotion, "
            "Build.FINGERPRINT tests) and makes them report \"real device\"."
        ),
        limits="Hardware-backed attestation can still detect the emulator.",
        verify_hint="Launch the app in the emulator: no \"unsupported device\" screen.",
        method_keywords=(
            "isemulator", "checkemulator", "detectemulator", "isemu",
            "isemulated", "emulatordetected",
        ),
        class_keywords=("emulator", "emulated", "genymotion", "virtual"),
        string_keywords=("goldfish", "genymotion", "generic_x86", "sdk_gphone", "vbox86", "bluestacks", "nox"),
        strategies=(STRATEGY_BOOLEAN_FALSE, STRATEGY_RETURN_ZERO),
        acceptable_returns=("Z", "I"),
        min_score=4,
        require_context=True,
        penalise_ui_names=True,
        tags=("security",),
    ),
    Objective(
        id="tracking",
        title="Disable analytics and tracking",
        tagline="Stop the app from reporting what you do",
        explanation=(
            "Finds the event-logging entry points of the analytics SDKs the app "
            "ships (Firebase, Facebook, Adjust, AppsFlyer, Amplitude, Mixpanel) "
            "and neutralises them."
        ),
        limits=(
            "Events already queued before patching, and server-side logging, "
            "are not covered. Some apps log through a shared generic method "
            "that also carries crash reports."
        ),
        verify_hint="Use the app for a few minutes, then check the app's network log is quieter.",
        method_keywords=(
            "logevent", "trackevent", "logscreen", "sendanalytics", "reportevent",
            "logpurchase", "trackpurchase", "setuserid", "logpage", "recordevent",
        ),
        class_keywords=("analytics", "tracking", "telemetry", "metrics", "logger"),
        string_keywords=("firebase_analytics", "adjust", "appsflyer", "amplitude", "mixpanel", "segment"),
        library_markers=(
            "com/google/firebase/analytics", "com/google/android/gms/analytics",
            "com/facebook/appevents", "com/adjust/sdk", "com/appsflyer",
            "com/amplitude/api", "com/mixpanel", "com/segment/analytics",
        ),
        strategies=(STRATEGY_CLEAR_BODY, STRATEGY_RETURN_VOID),
        acceptable_returns=("V",),
        min_score=4,
        tags=("privacy",),
    ),
    Objective(
        id="updates",
        title="Block forced updates",
        tagline="Keep using the version you patched",
        explanation=(
            "Finds the update prompts (isUpdateRequired, forceUpdate, "
            "needsUpdate) and makes them report \"no update needed\"."
        ),
        limits=(
            "If the app stops working when it is outdated, this patch only "
            "removes the prompt, not the compatibility block."
        ),
        verify_hint="Reopen the app after a few days: no blocking update screen.",
        method_keywords=(
            "isupdaterequired", "forceupdate", "needsupdate", "checkupdate",
            "isupdateneeded", "shouldupdate", "isoutdated", "showupdatedialog",
        ),
        class_keywords=("update", "upgrade", "version"),
        string_keywords=("update_required", "new_version", "force_update"),
        strategies=(STRATEGY_BOOLEAN_FALSE, STRATEGY_RETURN_VOID),
        acceptable_returns=("Z", "V"),
        min_score=4,
        require_context=True,
        penalise_ui_names=True,
        tags=("quality-of-life",),
    ),
    Objective(
        id="screenshot_watermark",
        title="Remove a watermark or overlay",
        tagline="Get clean screenshots and exports",
        explanation=(
            "Finds the code that draws a watermark logo or a persistent overlay "
            "(drawWatermark, addWatermark, showWatermark) and disables it."
        ),
        limits="Only overlays drawn by the app itself can be removed.",
        verify_hint="Take a screenshot or export: no logo in the corners.",
        method_keywords=("watermark", "drawwatermark", "addwatermark", "showwatermark", "drawlogo"),
        class_keywords=("watermark", "overlay", "logo"),
        string_keywords=("watermark",),
        strategies=(STRATEGY_CLEAR_BODY, STRATEGY_RETURN_VOID),
        acceptable_returns=("V",),
        min_score=4,
        require_context=True,
        tags=("quality-of-life",),
    ),
)

OBJECTIVES_BY_ID: Dict[str, Objective] = {objective.id: objective for objective in OBJECTIVES}


def get(objective_id: str) -> Objective:
    try:
        return OBJECTIVES_BY_ID[objective_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown objective '{objective_id}'. Available: {', '.join(OBJECTIVES_BY_ID)}"
        ) from exc


def _keyword_hits(text: str, keywords: Sequence[str]) -> List[str]:
    lowered = text.lower()
    return [keyword for keyword in keywords if keyword in lowered]


def match_text(user_text: str) -> List[Objective]:
    """Maps a free-form sentence ("remove the ads and the watermark") to objectives."""
    lowered = (user_text or "").lower()
    matches: List[Objective] = []

    for objective in OBJECTIVES:
        needles = (
            objective.id,
            objective.title.lower(),
            *objective.method_keywords[:6],
            *objective.class_keywords[:3],
        )
        if any(needle and needle in lowered for needle in needles):
            matches.append(objective)

    # Common phrasings that do not share a word with the objective title.
    aliases: Dict[str, str] = {
        "pub": "ads", "publicit": "ads", "sponsor": "ads", "banner": "ads",
        "payant": "premium", "paid": "premium", "abonnement": "premium",
        "subscription": "premium", "pro version": "premium", "achat": "premium",
        "capture": "screenshots", "screen capture": "screenshots", "record": "screenshots",
        "rooted": "root", "superuser": "root", "magisk": "root",
        "emulateur": "emulator", "blue stacks": "emulator", "bluestacks": "emulator",
        "telemetry": "tracking", "stats": "tracking", "analytics": "tracking",
        "update": "updates", "mise a jour": "updates",
        "logo": "screenshot_watermark", "filigrane": "screenshot_watermark",
    }
    for needle, objective_id in aliases.items():
        if needle in lowered:
            matches.append(OBJECTIVES_BY_ID[objective_id])

    seen = set()
    unique: List[Objective] = []
    for objective in matches:
        if objective.id not in seen:
            seen.add(objective.id)
            unique.append(objective)
    return unique


def custom_objective(keywords: Sequence[str]) -> Objective:
    """Builds a search profile from the user's own words."""
    cleaned = tuple(sorted({k.strip().lower() for k in keywords if k.strip()}))
    return Objective(
        id="custom",
        title="Custom search",
        tagline="Search the app for your own keywords",
        explanation="Searches method names, class names and text constants for the words you type.",
        limits="This is a best-effort search: review the suggested targets before building.",
        verify_hint="Test the exact screen where the behaviour should change.",
        method_keywords=cleaned,
        class_keywords=cleaned,
        string_keywords=cleaned,
        strategies=(STRATEGY_BOOLEAN_TRUE, STRATEGY_BOOLEAN_FALSE, STRATEGY_RETURN_VOID, STRATEGY_CLEAR_BODY),
        acceptable_returns=("Z", "V", "I", "J"),
        min_score=2,
        require_primary=False,
        tags=("advanced",),
    )


def choose_strategy(objective: Objective, return_type: str) -> str:
    """Picks the transformation that fits the method's return type."""
    order = {
        "Z": (STRATEGY_BOOLEAN_TRUE, STRATEGY_BOOLEAN_FALSE, STRATEGY_RETURN_ZERO, STRATEGY_CLEAR_BODY),
        "V": (STRATEGY_RETURN_VOID, STRATEGY_CLEAR_BODY),
        "I": (STRATEGY_RETURN_ZERO,),
        "J": (STRATEGY_RETURN_ZERO,),
        "F": (STRATEGY_RETURN_ZERO,),
        "D": (STRATEGY_RETURN_ZERO,),
        "L": (STRATEGY_RETURN_ZERO,),
    }.get(return_type, (STRATEGY_CLEAR_BODY,))

    for strategy in order:
        if strategy in objective.strategies:
            return strategy
    return objective.strategies[0]
