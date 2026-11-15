"""
Preference-key tracing: the evidence that survives obfuscation.

R8/ProGuard renames ``isPremiumUser()`` to ``a()``, so the heuristic scorer has
nothing to read. But the *string* it reads from ``SharedPreferences`` usually
survives: ``KEY_PREMIUM``, ``is_premium``, ``premium_user``. This module builds
an index of those keys and of the classes that own them, including nested
classes (Kotlin ``lazy { }`` lambdas compile to ``Outer$Inner``).

A method is then a premium candidate when:

* it is parameterless and returns a boolean/number, and
* either its own body carries the key, or its class (or a nested class) does.

No key is invented: every piece of evidence quotes the string found in the DEX.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Substrings that make a constant look like an entitlement stored in prefs.
# "licen" covers license/licence; "subscri" covers subscription/subscribed.
_STRONG_TOKENS: Tuple[str, ...] = (
    "premium", "licen", "subscri", "trial", "entitle", "vip",
    "ad_free", "adfree", "no_ads", "noads", "pro_version", "full_version",
    "is_pro",
)

# Words that also appear in analytics events ("ecommerce_purchase") and system
# actions ("USER_UNLOCKED"). They only count when the constant is shaped like a
# preference key (UPPER_SNAKE, or a known prefix such as is_/has_/key_).
_WEAK_TOKENS: Tuple[str, ...] = ("purchas", "paid", "unlock")

# First underscore-separated word of a legitimate preference key. Only state
# prefixes are listed: noun prefixes such as "subscription" are also used by
# analytics event names ("subscription_started").
_PREF_PREFIXES = frozenset({
    "is", "has", "key", "pref", "prefs", "user", "app", "setting", "settings",
    "flag", "show", "enable", "disable", "feature",
})

# Android intent actions, Firebase parameter names and package paths are not
# preferences, even when they contain an entitlement word.
_SYSTEM_PREFIXES = (
    "android.", "com.", "org.", "io.", "net.", "java.", "kotlin.", "dalvik.",
    "app_store_", "in_app_", "ecommerce_", "firebase_", "adjust_", "appsflyer_",
)

# Analytics event names are past-tense verbs: "subscription_started",
# "premium_purchased". Preference keys are states, not events.
_EVENT_SUFFIXES = (
    "_cancel", "_canceled", "_cancelled", "_convert", "_converted", "_renew",
    "_renewed", "_start", "_started", "_complete", "_completed", "_failed",
    "_failure", "_success", "_successful", "_refund", "_refunded", "_paused",
    "_resumed", "_viewed", "_clicked", "_shown", "_dismissed", "_purchased",
    "_subscribed", "_upgraded", "_activated",
)

# Method names used by SharedPreferences (and AndroidX wrappers) to read a value.
_READ_CALLS: Tuple[str, ...] = (
    "getboolean", "getint", "getlong", "getstring", "getfloat",
    "getall", "contains",
)

# Qualifiers that describe bookkeeping *around* a purchase (when it was last
# queried, whether a refresh is due) instead of the entitlement itself.
# "LAST_QUERY_PURCHASE_HISTORY_TIME" is a refresh throttle, not a paid flag, so
# a weak token must not be enough on its own when one of these is present.
_BOOKKEEPING_TOKENS = frozenset({
    "query", "history", "cache", "cached", "refresh", "sync", "timestamp",
    "last", "attempt", "attempts", "retry", "time", "date", "count", "timer",
})

_KEY_RE = re.compile(r"[A-Za-z0-9_.:\-]+")

# Analytics event vocabulary. An ALL-CAPS key containing one of these is a
# protobuf enum constant or a logging tag, not a stored flag
# ("DIAGNOSTIC_EVENT_TYPE_NATIVE_AD_REVENUE_SUBSCRIPTION_STARTED").
_EVENT_VOCABULARY = frozenset({
    "event", "events", "analytics", "tracking", "metric", "metrics", "log",
})

# Verbs that make a bare CamelCase string an event name rather than a key:
# Facebook's standard events are literally "StartTrial" and "SubscriptionRestore".
_ACTION_TOKENS = frozenset({
    "start", "started", "stop", "restore", "restored", "purchase", "purchased",
    "subscribe", "subscribed", "cancel", "cancelled", "renew", "renewed",
    "upgrade", "upgraded", "complete", "completed", "activate", "activated",
    "begin", "success", "failure", "error",
})


def _camel_words(text: str) -> List[str]:
    """Ordered lowercase words of a key, split on camelCase and separators."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    return [part for part in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if part]


def _word_tokens(text: str) -> Set[str]:
    """``LAST_QUERY_PURCHASE_HISTORY_TIME`` / ``hasPaidPlan`` -> lowercase words."""
    return set(_camel_words(text))

# Only methods that could be a decision point are indexed as readers. This is
# exactly the set the scanner decodes anyway, so the index is free.
_TRACEABLE_RETURNS = frozenset({
    "Z", "V", "I", "J", "F", "D", "Ljava/lang/String;",
})

# Class-level attribution is restricted to flags, not UI helpers.
_CLASS_LEVEL_RETURNS = frozenset({"Z", "I", "J"})

# A method whose own body carries the key can also be a void/String helper.
_METHOD_LEVEL_RETURNS = frozenset({
    "Z", "V", "I", "J", "F", "D", "Ljava/lang/String;",
})


def looks_like_preference_key(text: str) -> bool:
    """True for constants shaped like a stored entitlement key.

    ``KEY_PREMIUM`` / ``is_premium`` / ``premiumUser`` pass.
    ``Premium`` / ``subscription`` (bare display words) do not.
    """
    value = (text or "").strip()
    if not (3 <= len(value) <= 90):
        return False
    if not _KEY_RE.fullmatch(value):
        return False
    if value[0] in "._:-" or value[-1] in "._:-":
        return False
    lowered = value.lower()
    if lowered.startswith(_SYSTEM_PREFIXES):
        return False

    words_list = _camel_words(value)
    words = set(words_list)
    # A negated action is not an entitlement state: "playlistUnsubscriber"
    # contains "subscri" but says the opposite of "subscribed".
    if any(word.startswith("unsub") for word in words):
        return False
    # ALL-CAPS analytics / protobuf enum constants are events, not flags.
    if value.isupper() and words & _EVENT_VOCABULARY:
        return False

    first_word = lowered.split("_", 1)[0]
    pref_prefixed = "_" in lowered and first_word in _PREF_PREFIXES
    if not value.isupper() and not pref_prefixed and lowered.endswith(_EVENT_SUFFIXES):
        return False

    strong = any(token in lowered for token in _STRONG_TOKENS)
    weak = any(token in lowered for token in _WEAK_TOKENS)
    if not strong:
        if not weak:
            return False
        # A weak token inside a cache/timing key is bookkeeping, not a flag.
        if words & _BOOKKEEPING_TOKENS:
            return False
        # ``purchas``/``paid``/``unlock`` are also nouns ("PURCHASE_DETAILS_SET",
        # "purchaseToken"). Only a state prefix turns one into a stored flag:
        # ``is_purchased``, ``hasPaidPlan``, ``KEY_PURCHASE``.
        if not any(word in _PREF_PREFIXES for word in words_list[:2]):
            return False

    has_separator = any(char in value for char in "_.:-")
    mixed_case = bool(re.search(r"[a-z][A-Z]", value)) or bool(re.search(r"[A-Z]{2,}", value))
    if not (has_separator or mixed_case):
        # ``premium`` alone is usually a tag or a short label, not a key.
        return False
    if not has_separator and words & _ACTION_TOKENS and words_list[0] not in _PREF_PREFIXES:
        # Bare CamelCase starting with a verb is an event or a label
        # ("StartTrial", "SubscriptionRestore"), not a stored key.
        return False
    return True


def _outer_descriptor(descriptor: str) -> str:
    """``Laz4$a;`` -> ``Laz4;`` so nested lambdas belong to their owner."""
    base = descriptor
    while "$" in base:
        base = base.split("$", 1)[0] + ";"
    return base


def _calls_preferences(code: object) -> bool:
    called = getattr(code, "called_methods", ()) or ()
    for call in called:
        lowered = call.lower()
        if "sharedpreferences" in lowered:
            return True
        arrow = lowered.find("->")
        paren = lowered.find("(")
        if arrow == -1 or paren == -1:
            continue
        name = lowered[arrow + 2:paren]
        if name in _READ_CALLS:
            return True
    return False


def _reads_preferences_field(code: object) -> bool:
    for _op, _name, field_type in getattr(code, "field_accesses", ()) or ():
        if "sharedpreferences" in str(field_type).lower():
            return True
    return False


@dataclass
class PreferenceKey:
    """One key string and where it was found."""

    text: str
    classes: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {"key": self.text, "classes": self.classes, "methods": self.methods}


@dataclass(frozen=True)
class PreferenceEvidence:
    """Why a method is suspected to read a stored entitlement."""

    keys: Tuple[str, ...]
    source: str          # "method" (own body) or "class" (owner class / nested)
    detail: str


class PreferenceIndex:
    """Key -> class/method index, built in one pass over the DEX files."""

    def __init__(self) -> None:
        self.keys: Dict[str, PreferenceKey] = {}
        self._by_class: Dict[str, Set[str]] = defaultdict(set)
        self._by_method: Dict[str, Set[str]] = defaultdict(set)
        self._method_calls: Dict[str, List[str]] = {}
        # Classes that really touch SharedPreferences (accessor call or field).
        # A key string alone (an analytics event name, a system action) is not
        # enough to call a class a preference holder.
        self._prefs_aware: Set[str] = set()
        # Number of methods per class: class-level evidence is only credible for
        # small, focused holder classes, not for 50-method utility barrels.
        self._class_methods: Dict[str, int] = defaultdict(int)
        # Parameterless boolean/number getters seen while scanning. Keeping only
        # this shape bounds the index on large apps.
        self._getters: List[Tuple[str, str, str, str]] = []

    @classmethod
    def build(cls, dex_files: Iterable[object]) -> "PreferenceIndex":
        index = cls()
        for dex in dex_files:
            for method in dex.iter_methods():  # type: ignore[attr-defined]
                if not method.has_body:  # type: ignore[attr-defined]
                    continue
                index._class_methods[method.class_descriptor] += 1
                if method.return_type not in _TRACEABLE_RETURNS:  # type: ignore[attr-defined]
                    continue
                code = method.code()  # type: ignore[attr-defined]
                if code is None or not getattr(code, "complete", True):
                    continue

                descriptor = method.class_descriptor  # type: ignore[attr-defined]
                if _calls_preferences(code) or _reads_preferences_field(code):
                    index._prefs_aware.add(descriptor)
                    index._prefs_aware.add(_outer_descriptor(descriptor))

                return_type = method.return_type  # type: ignore[attr-defined]
                if (
                    return_type in _CLASS_LEVEL_RETURNS
                    and not method.parameters
                    and method.name not in ("<init>", "<clinit>")
                ):
                    index._getters.append(
                        (
                            method.full_name,
                            method.class_descriptor,
                            method.name,
                            return_type,
                        )
                    )

                found = [text for text in code.strings if looks_like_preference_key(text)]
                if not found:
                    continue

                full_name = method.full_name  # type: ignore[attr-defined]
                descriptor = method.class_descriptor  # type: ignore[attr-defined]
                for text in dict.fromkeys(found):
                    entry = index.keys.setdefault(text, PreferenceKey(text=text))
                    if descriptor not in entry.classes:
                        entry.classes.append(descriptor)
                    if full_name not in entry.methods:
                        entry.methods.append(full_name)
                    index._by_method[full_name].add(text)
                    index._by_class[descriptor].add(text)
                    outer = _outer_descriptor(descriptor)
                    if outer != descriptor:
                        index._by_class[outer].add(text)
                index._method_calls[full_name] = list(code.called_methods)
        return index

    # -- queries ----------------------------------------------------------------
    def keys_for_class(self, class_descriptor: str) -> List[str]:
        return sorted(self._by_class.get(class_descriptor, ()))

    def keys_for_method(self, full_name: str) -> List[str]:
        return sorted(self._by_method.get(full_name, ()))

    def evidence_for(self, method: object, vendored: bool = False) -> Optional[PreferenceEvidence]:
        """Returns the preference evidence for a candidate method, if any."""
        if vendored:
            return None
        if getattr(method, "parameters", ()):  # type: ignore[attr-defined]
            return None
        name = getattr(method, "name", "")
        if name in ("<init>", "<clinit>"):
            return None
        return_type = getattr(method, "return_type", "")

        full_name = getattr(method, "full_name", "")  # type: ignore[attr-defined]
        own_keys = self.keys_for_method(full_name)
        if own_keys and return_type in _METHOD_LEVEL_RETURNS:
            code = getattr(method, "code", lambda: None)()
            reads = _calls_preferences(code)
            # A string constant that merely *contains* "premiumUser" (a model's
            # toString, a serialized field name) is not proof of a preference
            # read. The method must touch SharedPreferences, directly or through
            # its own class.
            prefs_aware = (
                reads
                or _reads_preferences_field(code)
                or self._is_prefs_aware(getattr(method, "class_descriptor", ""))
            )
            if prefs_aware:
                detail = "the method reads " + ", ".join(f"'{key}'" for key in own_keys[:2])
                if reads:
                    detail += " through a preferences accessor"
                return PreferenceEvidence(tuple(own_keys), "method", detail)

        class_descriptor = getattr(method, "class_descriptor", "")  # type: ignore[attr-defined]
        class_keys = self.keys_for_class(class_descriptor)
        if (
            class_keys
            and return_type in _CLASS_LEVEL_RETURNS
            and len(class_keys) <= 4
            and self._class_methods.get(class_descriptor, 0) <= 12
            and self._is_prefs_aware(class_descriptor)
        ):
            detail = (
                "the class stores "
                + ", ".join(f"'{key}'" for key in class_keys[:2])
                + " in SharedPreferences; this parameterless getter exposes it"
            )
            return PreferenceEvidence(tuple(class_keys), "class", detail)

        return None

    def _is_prefs_aware(self, descriptor: str) -> bool:
        return (
            descriptor in self._prefs_aware
            or _outer_descriptor(descriptor) in self._prefs_aware
        )

    # -- reporting --------------------------------------------------------------
    def candidate_getters(self) -> List[Dict[str, object]]:
        """Parameterless boolean/number getters living in a keyed class."""
        found: List[Dict[str, object]] = []
        for full_name, descriptor, name, return_type in self._getters:
            keys = self._by_class.get(descriptor)
            if not keys:
                continue
            found.append(
                {
                    "method": full_name,
                    "class": descriptor,
                    "name": name,
                    "return_type": return_type,
                    "keys": sorted(keys),
                }
            )
        return found

    def to_dict(self) -> Dict[str, object]:
        return {
            "key_count": len(self.keys),
            "keys": [
                entry.to_dict()
                for entry in sorted(self.keys.values(), key=lambda item: item.text)
            ],
        }

    def __len__(self) -> int:
        return len(self.keys)
