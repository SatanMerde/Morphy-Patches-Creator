# Architecture

Morphy Patches Creator is a thin pipeline around a real static-analysis engine. Nothing in the analysis path calls a network service or a simulated result.

```
APK
 │
 ├─ core/apk.py ────────► zip container, manifest, DEX list, native libs, packers
 │        │
 │        ├─ core/axml.py ──► binary AndroidManifest.xml (package, version, SDK, permissions)
 │        └─ core/dex.py ───► strings, called methods, integer literals, field accesses, opcodes
 │
 ├─ core/preferences.py ─► entitlement keys (KEY_PREMIUM, is_premium) → owner class, getter
 │
 ├─ core/analysis.py ───► scores every method against the selected objectives
 │        │                 (camelCase tokens, SDK calls, blocking literals, preference keys)
 │        ├─ presets/objectives.py ──► what each goal means, and what change is safe
 │        └─ core/fingerprint.py ───► does the rendered fingerprint match exactly one method?
 │
 ├─ core/plan.py ───────► PatchPlan: chosen methods, plain-English actions, confidence, notes
 │
 ├─ synthesizer/kotlin.py ──► real app.morphe.patcher Kotlin source
 │        │                    (methodCall filter + version pin for obfuscated targets)
 │        │
 │        └─ core/xrefs.py ─► on-demand call graph used by MCP investigation tools
 │
 ├─ core/verifier.py ────► rejects @Patch / replaceMethod, weak fingerprints, bad brackets
 │
 └─ synthesizer/patch_writer.py
          ├─ copies sources into MorpheApp/morphe-patches-template
          ├─ runs :patches:buildAndroid (D8) when Java + Git + registry token exist
          └─ otherwise returns dist/morphy-project.zip with setup steps
```

## Why the parsers are hand-written

`core/dex.py` and `core/axml.py` implement only what the analysis needs:

- DEX: string/type/proto/method/class tables, class data, linear instruction decoding, `const-string`, `invoke-*`, `iget*`/`iput*`/`sget*`/`sput*` field accesses, integer constants and their `(opcode, register, value)` sites.
- AXML: string pool, resource map, start/end elements, typed attribute values.

This keeps installation to `pip install -e .`, works on Python 3.10–3.14 and on Windows without a compiler, and makes a full scan fast:

| APK | Methods | One goal | Every goal |
|---|---|---|---|
| Showly 3.72 (1 DEX, obfuscated) | 43 562 | ~1.7 s | ~3 s |
| Cryptomator 2.1 (9 DEX) | 342 279 | ~9 s | ~17 s |

The preference index and the fingerprint check reuse the method bodies the scan already decoded, so they add no second pass.

## Scoring model

A candidate needs a **primary signal**, otherwise it is discarded:

- a method-name token match (`isPremiumUser` → `is`, `premium`, `user`),
- a call into a known SDK (`com.android.billingclient`, Firebase Analytics, …),
- or a blocking literal used with the right call (`0x2000` + `addFlags`).

Context signals only corroborate: class-name tokens, text constants, return type, parameter count. Penalties apply to constructors, compiler-generated methods, obfuscated names, and vendored packages (`androidx`, `kotlin`, `com.google.android.material`, …).

Two filters keep the list honest on real apps:

- A method **inside a bundled SDK** (`com.qonversion`, `com.android.billingclient`, Firebase, …) is treated as vendored. Its own calls to that SDK no longer count as a primary signal, so the tool does not propose patching an SDK's internal `getDurationDays`.
- For "is this true?" goals, names that describe **display helpers** (`…Hint`, `…Banner`, `get…Label`) are penalised, and generic plumbing (`equals`, `hashCode`, `accept`) is ignored. `getHasSubscriptionUpgradeHint` controls an upsell banner, not the entitlement.

Objectives that are easy to confuse (`premium`, `root`, `emulator`, `updates`, `watermark`) additionally require textual or library context, which is what stops `FilePathComponents.isRooted` from being reported in an app that does no root detection.

Each objective keeps at most six candidates, and at most two per class.

### Preference-key evidence (the part that survives R8)

Obfuscation renames `isPremiumUser()` to `a()`, so name matching returns nothing. The key the method reads from `SharedPreferences` usually survives: `KEY_PREMIUM`, `is_premium`, `premiumUser`.

`core/preferences.py` builds one index per scan and treats a constant as an entitlement key only when it is shaped like a stored key (separator or camelCase) and is not an analytics event or a system action:

- **Strong tokens** (`premium`, `licen`, `subscri`, `trial`, `entitle`, `vip`, `ad_free`, `no_ads`, …) pass on shape alone.
- **Weak tokens** (`purchas`, `paid`, `unlock`) also need a key shape (`UPPER_SNAKE` or a state prefix such as `is_`/`has_`/`key_`).
- Rejected: package/intent prefixes (`android.`, `com.`, `app_store_`, `in_app_`, `firebase_`), analytics event suffixes (`_started`, `_cancel`, `_purchased`, …), and URL-looking strings.

A candidate gets preference evidence in two ways:

1. **Method level** — the parameterless method itself carries the key (`isTrialExpired` reads `trialExpired`). Strongest signal, and the key becomes a fingerprint anchor.
2. **Class level** — the class owns the key and the method is a parameterless `Z`/`I`/`J` getter. To avoid flagging analytics barrels, the class must really touch `SharedPreferences` (accessor call or field), hold at most four keys, and declare at most twelve methods.

### Boolean polarity

`choose_strategy` reads the method name before answering. `hasPaidLicense` must answer "yes"; `isTrialExpired` must answer "no"; `hasNoAds` is the positive ad-free state. The objective's strategy order is the baseline, and a small polarity check flips it — so the generated Kotlin says `returnEarly(false)` for `isTrialExpired` instead of granting a false entitlement.

### Call graph and investigation

`core/xrefs.py` indexes forward and reverse edges over the APK's **own** methods; framework calls are skipped because they add no investigative value. It is built on demand (MCP `morphy_xrefs`, CLI `investigate`), never during the normal scan.

- Signature grouping (overrides, interface implementations) is disabled for obfuscated names (`a`, `az4`): an R8 `a()Z` is not an override, it is a coincidence.

`core/investigate.py` turns a goal into an evidence dossier: for each candidate it quotes the preference key, literal, distinctive string or name match that supports it, plus its callers and callees. Evidence is ranked `strong` (method-level key, literal, name match, distinctive string), `moderate` (class-level key, SDK call), `weak` (context only) and `none`. Only `strong` and `moderate` are recommended, so the CLI and an AI agent follow the same rule: **no evidence, no patch**.

### Fingerprint uniqueness

A patch is only as good as its fingerprint. After the scan, `core/fingerprint.py` re-counts how many methods the rendered fingerprint would match in the same APK:

| Verdict | Meaning | Action |
|---|---|---|
| `unique` | exactly one method | used as is |
| `ambiguous` | several methods share class + name + strings | kept, with a plan note to add a distinctive string |
| `missing` | zero methods match | discarded, with a warning in `REPORT.txt` |
| `generic-anchor` | one anchor is reused by >200 methods | kept, with a stability warning |

Obfuscated targets also get a structural `methodCall(...)` filter in their fingerprint, and `AppTarget(version = …)` pinning, because their class and method names change on every release.

## Honesty boundary

The verifier and the writer share one rule: never produce something that looks installable but is not.

- `@Patch` and `replaceMethod` do not exist in the current Morphe API, so the verifier treats them as errors.
- A `.mpp` without `classes.dex` is rejected by Morphe Manager, so the writer only returns `kind="mpp"` after a successful `buildAndroid`, and otherwise returns `kind="project"` with explicit next steps.
- When Kotlin reports a **missing import** for a symbol the synthesizer itself emits, the writer adds that exact import and retries (up to three attempts). It never invents an API or edits patch logic, and the automatic change is printed and written to `REPORT.txt`.
