---
name: morphe-patch-creator
description: Expert skill for autonomously reverse engineering Android APKs and synthesizing production-ready Kotlin patches for the Morphe ecosystem (.mpp).
metadata:
  version: "1.0.0"
---

# Morphe Patch Creator Skill

Use this skill when tasked with reverse engineering an Android APK, identifying feature gates, creating resilient bytecode modifications, or compiling `.mpp` patch bundles for Morphe.

## Workflow

1. **Ingest & Disassemble**:
   Run `morphy-creator unpack <app.apk> -o ./workspace` to extract `AndroidManifest.xml`, decode resources, and disassemble Smali bytecode via Apktool.
   Optionally run JADX decompilation for high-level Java viewing.

2. **Locate Target Logic**:
   - Use Androguard or REA inspection to discover classes and methods associated with the requested feature (e.g. `isPremium`, `showAd`, `FLAG_SECURE`).
   - Identify stable opcode sequences and string constants.

3. **Synthesize Resilient Patch**:
   - Create a typed Kotlin patch conforming to `BytecodePatch`.
   - Never rely on obfuscated class names directly; bind them via `Fingerprint`.
   - Replace or modify instructions cleanly with `replaceMethod` or `replaceInstructions`.

4. **Verify & Compile**:
   Compile the bundle using `morphy-creator build ./patches -o ./build/patches.mpp`.
