# ⚠️ Capabilities & Technical Limitations

Understanding both the capabilities and the technical boundaries of **Morphy Patches Creator** ensures realistic expectations and efficient patch development.

---

## 🎯 What Morphy Patches Creator Can Do (Capabilities)

### 1. Ingestion & Multi-DEX Reconstitution (via Apktool)
- **Universal APK Decoding**: Unpacks monolithic APKs as well as modern split bundle sets (APKM, APKS, base + dynamic feature modules).
- **Binary XML Reconstitution**: Converts obfuscated binary `AndroidManifest.xml` into human-readable XML with exact namespace preservation.
- **Resource Table ID Resolution**: Resolves internal IDs in `resources.arsc` (strings, layouts, drawables, colors) to locate UI elements, preference toggles, and feature gate names.
- **Baksmali Disassembly**: Emits clean Smali bytecode and AST structures across all `classes.dex`, `classes2.dex`, ..., `classesN.dex`.

### 2. Deep Native & Binary Introspection (via REA)
- **Shared Object (.so) Inspection**: Analyzes native C/C++ libraries (ARM64-v8a, ARMeabi-v7a, x86_64) embedded inside the target app.
- **JNI Export Resolution**: Maps native methods declared in Java/Kotlin (`native fun ...`) to their C/C++ implementations (`Java_com_package_class_method`).
- **Call-Graph & Cross-Reference Mapping**: Traces caller-callee chains to uncover hidden entitlement checks, cryptographic verification routines, and checksum validation routines.
- **Il2Cpp Metadata Extraction**: Resolves method names, field offsets, and classes for Unity-based Android applications.

### 3. Cognitive Patch Synthesis (via Morphe-AI)
- **Resilient Fingerprinting**: Generates opcode-sequence and string matchers that survive ProGuard, R8, and DexGuard renaming updates across app releases.
- **Idiomatic Kotlin Patch Code**: Automatically produces typed, idiomatic Morphe patch definitions inheriting from `BytecodePatch`, `ResourcePatch`, or `SettingsPatch`.
- **Instruction Replacements**: Creates clean `replaceMethod`, `replaceInstructions`, or register override blocks targeting Morphe's patching engine.
- **Automated Bundle Packaging**: Coordinates Gradle compilation into production-ready `.mpp` patch bundles.

---

## ⚠️ What Morphy Patches Creator Cannot Do (Technical Boundaries)

### 1. Server-Side Entitlement & Cloud Verification
- **The Boundary**: Morphy patches operate entirely **client-side** (on the local Android device). If a feature, content stream, or subscription is verified, decrypted, or served directly by an authoritative remote backend server, modifying client-side bytecode will not grant access.
- **Example**:
  - ✅ **Client-side UI Gate**: `if (user.isPremium) showFeature()` -> Fully patchable.
  - ❌ **Server-side Token Verification**: Server requires a cryptographically signed receipt from Google Play's backend before returning media files -> Cannot be bypassed on the client.

### 2. Heavy Commercial Packers & Virtual Machine Protectors (VMP)
- **The Boundary**: Apps protected with kernel-level or aggressive commercial packing solutions (e.g. *SecNeo, Bangcle, Tencent Legu, DexGuard Enterprise O-LLVM*) encrypt the Dex files on disk and decrypt them only in memory at runtime.
- **Mitigation**: Morphy Patches Creator requires unencrypted Dex bytecode. For packed applications, developers must first obtain an unpacked memory dump (e.g., via dynamic runtime dumping tools or Frida hooks) before running Morphy's analysis pipeline.

### 3. Hardware-Backed Play Integrity & StrongBox Attestation
- **The Boundary**: Google Play Integrity checks utilizing hardware-backed security (TEE, SE, or StrongBox KeyMint) cannot be satisfied solely through Dalvik/Smali bytecode patches, as verification occurs at the operating system cryptographic boundary.
- **Mitigation**: Hardware attestation bypasses require system-level modifications (such as Zygisk / Magisk modules or patched kernels) rather than standalone application patches.

### 4. Code Downloaded Dynamically at Runtime (Dynamic Code Loading)
- **The Boundary**: Some applications download dynamic payloads, feature plugins, or scripts over the network during runtime. Morphy's static analysis inspects the APK package as delivered; dynamically fetched payloads require dynamic memory tracing via REA during an active session.

---

## 📊 Summary Matrix

| Feature / Scenario | Supported? | Engine Responsible | Notes |
| :--- | :---: | :--- | :--- |
| Split APKs (APKM / APKS) | ✅ **Yes** | Apktool Bridge | Merges and decompiles unified project |
| Resource & String Overrides | ✅ **Yes** | Apktool + Morphe | Replaces layouts, strings, and assets |
| Obfuscated Smali (R8/ProGuard) | ✅ **Yes** | Morphe-AI | Generates fuzzy opcode fingerprints |
| Native JNI Boundary Tracing | ✅ **Yes** | REA Engine | Maps `.so` symbols to Java methods |
| Unity / Il2Cpp Logic Inspection | ✅ **Yes** | REA Engine | Analyzes `global-metadata.dat` offsets |
| Local Paywall / Trial Expiry | ✅ **Yes** | Morphe-AI Synthesizer | Bypasses local boolean verifications |
| Dry-Run AST Patch Validation | ✅ **Yes** | Pipeline Core | Simulates patch execution before build |
| Server-Side API Enforcement | ❌ **No** | N/A | Requires authoritative backend response |
| Commercial Kernel Packers | ⚠️ **Partial** | REA Runtime | Requires dynamic dump before ingestion |
| Hardware TEE Attestation | ❌ **No** | N/A | Requires OS/Kernel-level modules |
