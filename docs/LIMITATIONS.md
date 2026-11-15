# Capabilities and limitations

## What it does well

| Capability | How it is implemented |
|---|---|
| Reads any APK / `.apkm` / `.xapk` / `.apks` | `zipfile` + hand-written AXML/DEX readers |
| Package, version, SDK, permissions, activities | binary `AndroidManifest.xml` decoded natively |
| Detects packers and anti-tamper markers | class/lib heuristics reported, never guessed around |
| Finds feature gates | tokenised method names + SDK calls + literal sites + preference keys |
| Handles multi-DEX apps | every `classesN.dex` is scanned once |
| Survives obfuscation | preference-key tracing, SDK calls and literals work without names |
| Answers "who calls this?" | on-demand call graph (`morphy_xrefs`) over the app's own methods |
| Explains its evidence | `investigate` dossier ranks strong / moderate / weak / none |
| Checks its own fingerprints | every candidate must match exactly one method in the APK |
| Writes current-API Kotlin | `patch(...)`, `Fingerprint`, `returnEarly`, `replaceInstruction` |
| Rejects stale API | verifier fails on `@Patch` / `replaceMethod` |
| Compiles a real `.mpp` | official `buildAndroid` (D8) through the template project |
| Explains itself | `REPORT.txt` with reasons, confidence and manual test steps |

## What it cannot do

### 1. Server-side entitlements
A patch changes local decisions only. If the backend verifies a purchase, signs a receipt, or serves media only to entitled accounts, the client cannot grant access.

- Patchable: `if (user.isPremium) showFeature()`
- Not patchable: the server refuses the request until Google Play confirms a valid token

### 2. Hardware attestation
Play Integrity strong verdict, KeyMint/StrongBox and TEE-backed checks execute below the app. They need system-level solutions, not a bytecode patch. The `root` and `emulator` goals explicitly say so in their limits.

### 3. Commercial packers
Legu, Jiagu, SecNeo, Bangcle and DexGuard-class protectors encrypt DEX files and decrypt them in memory. The tool detects and reports the protection; it does not fabricate targets. An unpacked dump is required first.

### 4. Code loaded at runtime
Bytecode downloaded after launch is invisible to static analysis. Only a dynamic trace (Frida, runtime dumping) can reach it.

### 5. Native-only decisions
A decision made entirely inside a `.so` is out of scope. The tool lists native libraries and flags suspicious ones, but Morphe patches operate on Dalvik bytecode.

### 6. Fragile fingerprints
If a method's name, class, text and literals all change between versions, the fingerprint stops matching. Three things reduce the risk without pretending it is gone:

- **Uniqueness pass.** Every candidate is re-matched against the APK it came from. A fingerprint that matches zero methods is discarded (and reported), one that matches several is flagged, and an anchor shared with more than 200 methods is marked unstable.
- **Structural filters.** When an obfuscated getter has no text anchor, the fingerprint gets a `methodCall(...)` filter (e.g. the delegate it calls) instead of relying on the class and method names alone.
- **Version pinning.** A patch whose target class or method is an R8 name (`az4`, `a`) declares `AppTarget(version = "…")`, so it is not silently applied to a version it was never verified on.

No static tool can guarantee an update-proof match; the verifier still warns when a `Fingerprint` relies on a single signal.

### 7. Universal goals
"Remove ads" covers the common client-side pattern. Ad SDKs that decide server-side, or that stitch video server-side, will keep showing ads. Some apps route analytics through a shared method that also carries crash reports; disabling it may lose crash data — the report says when that risk applies.

### 8. Decisions hidden inside a bundled SDK
Some apps delegate purchases or analytics to an SDK and keep no local check of their own. The only remaining match is then inside the SDK. The tool reports **"SDK found, no hook"** rather than suggesting an internal method: patching SDK internals is unreliable and breaks on every SDK update. `--details` names the SDK so the reason is visible.

The preference-key pass often recovers the app's *own* entitlement check even when the billing UI lives in an SDK: the key the app writes after a purchase (`KEY_PREMIUM`) is stored by app code, in a small holder class, not by the SDK. That is why an obfuscated app such as Showly 3.72 still yields exactly one target (`az4.a`) for the premium goal, while `morphy_preferences` shows the evidence.

## Summary

| Scenario | Supported | Notes |
|---|---|---|
| Split APKs | Yes | base APK extracted or analysed directly |
| Local paywall / trial | Yes | boolean/local checks |
| Local root / emulator checks | Yes | hardware-backed checks excluded |
| `FLAG_SECURE` screenshots | Yes | literal `0x2000` removed |
| Analytics SDK entry points | Yes | may include shared crash logging |
| Forced-update prompts | Yes | server compatibility blocks excluded |
| Watermarks drawn by the app | Yes | native/OS overlays excluded |
| Server-side enforcement | No | nothing to patch locally |
| Packed DEX | No | needs an unpacked dump |
| Hardware attestation | No | needs OS/kernel level |
