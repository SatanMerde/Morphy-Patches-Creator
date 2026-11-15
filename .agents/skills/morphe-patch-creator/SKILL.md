---
name: morphe-patch-creator
description: Create Morphe patches for Android apps from a plain-English goal, using real static analysis of the APK and the current app.morphe.patcher API.
metadata:
  version: "2.0.0"
---

# Morphe Patch Creator

Use this skill when the user wants a Morphe patch (`.mpp`) for an Android app, or asks what is patchable in an APK.

## Workflow

1. **Find the right goal.**
   `morphy-creator recipes` lists ids: `ads`, `premium`, `screenshots`, `root`, `emulator`, `tracking`, `updates`, `screenshot_watermark`; `custom` searches the user's own words.

2. **Analyse before generating.**
   `morphy-creator inspect <app.apk> --details`
   This writes nothing. Read the evidence per candidate. If nothing scores, say so; do not invent a target.

3. **Create the patch.**
   `morphy-creator create <app.apk> --for ads,premium -y -o <folder>`
   or `morphy-creator auto <app.apk> --prompt "remove ads and screenshots"`.

4. **Check the generated source.**
   `morphy-creator verify <file.kt>` — a score below 80 means a fragile fingerprint or missing `compatibleWith`.

5. **Compile.**
   `morphy-creator build <folder>`. Report the returned `kind`:
   - `mpp` → installable bundle;
   - `project` → sources plus the missing step (JDK 17+, Git, or a GitHub token with `read:packages`).

## API facts to respect

- A patch is a public top-level `val x = patch(name = "...", description = "...") { execute { ... } }`.
- `@Patch`, `BytecodePatch`, `ResourcePatch`, `replaceMethod` **do not exist**. Anything using them will not compile.
- Use `Fingerprint(...)` + `.match()`, `returnEarly(...)`, `replaceInstruction(index, "smali")`, `compatibleWith(Compatibility(...))`.
- Class files must target Java 17 or lower.

## Limits to mention to the user

Server-verified purchases, hardware attestation, commercial packers, and runtime-downloaded code cannot be patched from the client. Never promise otherwise.
