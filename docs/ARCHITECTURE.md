# Architecture

Morphy Patches Creator is a thin pipeline around a real static-analysis engine. Nothing in the analysis path calls a network service or a simulated result.

```
APK
 │
 ├─ core/apk.py ────────► zip container, manifest, DEX list, native libs, packers
 │        │
 │        ├─ core/axml.py ──► binary AndroidManifest.xml (package, version, SDK, permissions)
 │        └─ core/dex.py ───► strings, called methods, integer literals, opcodes per method
 │
 ├─ core/analysis.py ───► scores every method against the selected objectives
 │        │                 (camelCase token matching, SDK calls, blocking literals)
 │        └─ presets/objectives.py ──► what each goal means, and what change is safe
 │
 ├─ core/plan.py ───────► PatchPlan: chosen methods, plain-English actions, confidence
 │
 ├─ synthesizer/kotlin.py ──► real app.morphe.patcher Kotlin source
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

- DEX: string/type/proto/method/class tables, class data, linear instruction decoding, `const-string`, `invoke-*`, integer constants and their `(opcode, register, value)` sites.
- AXML: string pool, resource map, start/end elements, typed attribute values.

This keeps installation to `pip install -e .`, works on Python 3.10–3.14 and on Windows without a compiler, and makes a full scan fast:

| APK | Methods | Time |
|---|---|---|
| Showly 3.72 (1 DEX) | 43 562 | ~2.5 s |
| Cryptomator 2.1 (9 DEX) | 342 279 | ~17 s |

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

## Honesty boundary

The verifier and the writer share one rule: never produce something that looks installable but is not.

- `@Patch` and `replaceMethod` do not exist in the current Morphe API, so the verifier treats them as errors.
- A `.mpp` without `classes.dex` is rejected by Morphe Manager, so the writer only returns `kind="mpp"` after a successful `buildAndroid`, and otherwise returns `kind="project"` with explicit next steps.
