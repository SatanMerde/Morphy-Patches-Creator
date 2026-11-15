# Capabilities and limitations

## What it does well

| Capability | How it is implemented |
|---|---|
| Reads any APK / `.apkm` / `.xapk` / `.apks` | `zipfile` + hand-written AXML/DEX readers |
| Package, version, SDK, permissions, activities | binary `AndroidManifest.xml` decoded natively |
| Detects packers and anti-tamper markers | class/lib heuristics reported, never guessed around |
| Finds feature gates | tokenised method names + SDK calls + literal sites |
| Handles multi-DEX apps | every `classesN.dex` is scanned once |
| Survives obfuscation | text constants, SDK calls and literals work without names |
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
If a method's name, class, text and literals all change between versions, the fingerprint stops matching. The verifier warns when a Fingerprint relies on a single signal, but no static tool can guarantee an update-proof match.

### 7. Universal goals
"Remove ads" covers the common client-side pattern. Ad SDKs that decide server-side, or that stitch video server-side, will keep showing ads. Some apps route analytics through a shared method that also carries crash reports; disabling it may lose crash data — the report says when that risk applies.

### 8. Decisions hidden inside a bundled SDK
Some apps delegate purchases or analytics to an SDK and keep no local check of their own. The only remaining match is then inside the SDK. The tool reports **"SDK found, no hook"** rather than suggesting an internal method: patching SDK internals is unreliable and breaks on every SDK update. `--details` names the SDK so the reason is visible.

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
