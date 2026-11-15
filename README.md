<div align="center">

<img src="assets/logo.png" alt="Morphy Patches Creator" width="160"/>

# Morphy Patches Creator

**Turn a plain-English goal into a Morphe patch — without writing code.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()
[![Ecosystem](https://img.shields.io/badge/Ecosystem-Morphe%20Patcher-orange.svg)](https://github.com/MorpheApp)

</div>

---

## What this is

Morphy Patches Creator is a guided assistant for building [Morphe](https://github.com/MorpheApp) patches.

You answer four questions:

1. Which app? (drop an `.apk` on the window)
2. What should change? (pick a goal such as "remove ads")
3. Review what was found — every target comes with the reason it was picked
4. Done: get the patch code, a plain-English report, and an installable `.mpp` when the build tools are available

You do **not** need to know Kotlin, smali, or how Android is built. You **do** get to see and approve the exact methods that will be changed.

> **Honest by design.** The analysis is real: it reads the app's own DEX bytecode, never a mock. If a `.mpp` cannot be compiled on your machine, the tool says so and gives you a ready-to-build project — it never hands you a fake bundle.

---

## Quick start (Windows)

```powershell
git clone https://github.com/SatanMerde/Morphy-Patches-Creator.git
cd Morphy-Patches-Creator
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\morphy-creator.exe
```

That last command starts the wizard. On Linux/macOS use `python -m venv .venv`, `source .venv/bin/activate`, `pip install -e .`, then `morphy-creator`.

Check the environment at any time:

```powershell
morphy-creator doctor
```

`doctor` tells you, in plain words, what is ready and what is missing — and only flags as required the things the pipeline actually uses.

---

## The wizard, step by step

```
Step 1 of 4 - Which app?
  Drag the .apk file into this window, or paste its path.

Step 2 of 4 - What should the patch do?
  1  Remove ads                                  - Hide banners, interstitials and rewarded videos
  2  Unlock premium / paid features              - Bypass in-app purchase and subscription checks
  3  Allow screenshots                           - Stop the app from blocking screen capture
  4  Bypass root detection                       - Let the app run on a rooted phone
  5  Bypass emulator detection                   - Let the app run inside an emulator or on a PC
  6  Disable analytics and tracking              - Stop the app from reporting what you do
  7  Block forced updates                        - Keep using the version you patched
  8  Remove a watermark or overlay               - Get clean screenshots and exports
  a  Something else                              - describe it in your own words
```

You can answer `1,3` to combine goals, or write a sentence:

```
Choose one or more numbers (example: 1,3), or a
> remove the ads and let me take screenshots

I understood: Remove ads, Allow screenshots
Use these? [Y/n]:
```

Then the tool reads the app and shows a table like this:

```
+------------------------------------------------------------------------------+
|                            What I found in the app                           |
+------------------+----------------+---------------------------------+--------+
| Goal             | Result         | Best target                     | Trust  |
|------------------+----------------+---------------------------------+--------|
| Allow screenshots| 4 candidate(s)  | ...BaseActivity.onResume        | high   |
+------------------+----------------+---------------------------------+--------+
```

…followed by the plan in plain English:

```
Plan
  Allow screenshots - Finds code that adds the FLAG_SECURE window flag…
    * org.example.BaseDialog.onViewCreated: remove the blocking flag
    * org.example.BaseActivity.onResume: remove the blocking flag
```

Nothing is written until you confirm.

---

## Supported goals

| id | Goal | What it really changes | Typical limits |
|---|---|---|---|
| `ads` | Remove ads | Ad decision methods (`showAd`, `isAdLoaded`, …) return "no" / do nothing | Server-side ad stitching, some video ads |
| `premium` | Unlock premium | Local checks (`isPremium`, `hasSubscription`, …) answer "yes" | Server-verified purchases |
| `screenshots` | Allow screenshots | Removes the `FLAG_SECURE` window flag (literal `0x2000`) | Apps that blank the screen with a custom overlay |
| `root` | Bypass root detection | Root checks (`isRooted`, RootBeer, su lookups) report "not rooted" | Hardware attestation, Play Integrity strong verdict |
| `emulator` | Bypass emulator detection | Emulator checks report "real device" | Hardware attestation |
| `tracking` | Disable analytics | Analytics entry points (`logEvent`, `trackEvent`, …) are neutralised | Server-side logging; shared crash-report methods |
| `updates` | Block forced updates | Update prompts (`isUpdateRequired`, `forceUpdate`, …) answer "no" | Compatibility blocks that disable the app |
| `screenshot_watermark` | Remove watermark/overlay | Watermark drawing methods do nothing | Overlays rendered outside the app |
| `custom` | Anything else | Searches method names, class names and text for your own words | Best-effort; review the suggestions |

Every candidate is scored on concrete evidence: a method-name match, a call into a known SDK, a blocking literal, plus contextual corroboration. Constructors, vendored libraries (`androidx`, `kotlin`, …), look-alike names (`isAdded` vs `isAd`), and methods *inside* a bundled SDK are filtered out or demoted, so the plan points at the app's own decision, not an SDK's internal helper.

---

## Commands

| Command | Purpose |
|---|---|
| `morphy-creator` | Interactive wizard (the recommended path) |
| `morphy-creator inspect app.apk` | Analyse only, write nothing (`--details` shows the evidence) |
| `morphy-creator create app.apk --for ads,premium -y` | Same pipeline, non-interactive |
| `morphy-creator auto app.apk --prompt "remove ads and screenshots"` | Goal in plain words |
| `morphy-creator build <folder>` | Compile generated patches into a `.mpp` |
| `morphy-creator verify <file.kt>` | Structural/API check on one patch file |
| `morphy-creator unpack app.apk` | Apktool decompilation (manifest, resources, smali) |
| `morphy-creator merge bundle.apkm` | Extract the base APK from a split bundle |
| `morphy-creator recipes` | List the goals with their ids |
| `morphy-creator doctor` | Check Python / Java / Git / Apktool / JADX / registry token |
| `morphy-creator mcp` | Start the MCP server for AI assistants |

Every command accepts `--help`. Add `--debug` to any failing command to see the technical traceback.

---

## What you get

```
morphy-output/
├── src/
│   └── app/morphe/patches/screenshots/AllowScreenshotsPatch.kt
├── dist/
│   ├── patches-1.0.0.mpp          <- installable bundle (when the build can run)
│   └── morphy-project.zip         <- otherwise: sources + setup steps
├── project/                        <- official Morphe template project
└── REPORT.txt                      <- plain-English report: targets, reasons, limits
```

### Getting a real `.mpp`

A Morphe `.mpp` is a JAR that contains **compiled** patch classes plus a `classes.dex` produced by D8. Producing it requires the official Morphe Gradle toolchain:

1. **JDK 17 or newer** on `PATH`
2. **Git** (to fetch `MorpheApp/morphe-patches-template`)
3. **A GitHub token with `read:packages`**, because Morphe publishes its Gradle plugin and patcher in a private GitHub Packages registry

Add the token once:

```properties
# %USERPROFILE%\.gradle\gradle.properties
gpr.user=your-github-username
gpr.key=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Or set the `GITHUB_TOKEN` environment variable. Then:

```powershell
morphy-creator build .\morphy-output
# -> patches\build\libs\patches-<version>.mpp copied to .\morphy-output\dist\
```

Without the token, `build` returns `dist/morphy-project.zip` plus the exact steps above. That is a deliberate choice: an `.mpp` without `classes.dex` is rejected by Morphe Manager, so shipping one would only waste your time.

### Installing the patch

1. Copy the `.mpp` to your phone.
2. Open **Morphe Manager**, import the bundle, select the app.
3. Apply, then reinstall the app when asked.
4. If something breaks, uninstall and reinstall the original APK — that restores the unpatched app.

---

## What a generated patch looks like

Generated code targets the current API (`app.morphe.patcher`). There is **no `@Patch` annotation** and **no `replaceMethod`** in this API — a patch is a public top-level `val` created by `patch(...)`:

```kotlin
package app.morphe.patches.screenshots

import app.morphe.patcher.Fingerprint
import app.morphe.patcher.literal
import app.morphe.patcher.match
import app.morphe.patcher.extensions.InstructionExtensions.replaceInstruction
import app.morphe.patcher.patch.Compatibility
import app.morphe.patcher.patch.patch

@Suppress("unused")
val allowScreenshotsPatch = patch(
    name = "Allow screenshots",
    description = "Stop the app from blocking screen capture.",
    default = true,
) {
    compatibleWith(Compatibility("org.example.app", "app"))

    execute {
        // org.example.BaseActivity.onResume: remove the blocking flag
        val target1 = onResumeFingerprint.match()
        val index1 = target1.instructionMatches.first().index
        target1.method.replaceInstruction(index1, "const/16 v4, 0x0")
    }
}

private object onResumeFingerprint : Fingerprint(
    definingClass = "Lorg/example/BaseActivity;",
    name = "onResume",
    returnType = "V",
    parameters = listOf(),
    filters = listOf(literal(8192)),
)
```

The header comment names the app, the method, and why it was chosen. A developer can read it; you never have to.

---

## What it cannot do

- **Server-side entitlements.** If a paid feature is verified by a backend, no client patch grants it.
- **Hardware attestation.** Play Integrity strong verdict / TEE checks are outside Dalvik bytecode.
- **Packed code.** Legu, Jiagu, SecNeo, DexGuard-class protectors encrypt DEX files; the analysis reports the protection instead of guessing.
- **Dynamically loaded code.** Bytecode fetched at runtime is invisible to static analysis.
- **Fake bundles.** If compilation is impossible, you get sources and instructions, never a `.mpp` that pretends to work.

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for the detailed breakdown.

---

## AI assistants (MCP)

`morphy-creator mcp` exposes nine tools over the Model Context Protocol:

| Tool | Purpose |
|---|---|
| `morphy_list_goals` | List supported goals |
| `morphy_inspect_apk` | Analyse an APK and explain what is patchable |
| `morphy_create_patch` | Analyse → generate Kotlin → self-check → package |
| `morphy_xrefs` | Call graph: who calls a method, and what it calls |
| `morphy_search_strings` | Find the methods that contain a given text constant |
| `morphy_preferences` | Entitlement-like preference keys and the getters that expose them |
| `morphe_unpack_apk` | Apktool decompilation |
| `morphe_decompile_java` | JADX decompilation |
| `morphe_build_bundle` | Compile generated sources into a `.mpp` |

The three investigation tools exist so an AI assistant can follow evidence instead of guessing: search a string (`KEY_PREMIUM`) → list the methods that contain it → walk the call graph to the activity that consumes it. The engine only returns facts read from the APK.

Example OpenCode / Claude Desktop configuration:

```jsonc
{
  "mcp": {
    "morphy": {
      "type": "local",
      "command": ["C:\\path\\to\\Morphy-Patches-Creator\\.venv\\Scripts\\morphy-creator.exe", "mcp"],
      "enabled": true,
      "timeout": 600000
    }
  }
}
```

---

## Project structure

```
Morphy-Patches-Creator/
├── morphy_creator/
│   ├── cli.py                  # wizard + commands
│   ├── mcp_server.py           # MCP server (9 tools)
│   ├── doctor.py               # environment checks
│   ├── config.py               # Apktool/Java paths
│   ├── core/
│   │   ├── dex.py              # dependency-free DEX parser (strings, calls, literals, fields)
│   │   ├── axml.py             # dependency-free binary AndroidManifest reader
│   │   ├── apk.py              # APK container: package, SDK, packers, .so list
│   │   ├── analysis.py         # scoring engine (camelCase tokens, evidence)
│   │   ├── xrefs.py            # call graph: callers / callees / implementations
│   │   ├── preferences.py      # entitlement preference-key tracing
│   │   ├── fingerprint.py      # fingerprint uniqueness against the APK
│   │   ├── plan.py             # patch plan: naming, confidence, de-duplication
│   │   ├── verifier.py         # API/structural check of generated Kotlin
│   │   ├── agent.py            # PatchAgent.create: whole pipeline in one call
│   │   ├── split_merger.py     # .apkm/.xapk/.apks handling
│   │   └── subprocess_utils.py # Windows-safe launcher for .cmd/.bat tools
│   ├── presets/objectives.py   # the goal catalogue (signals, strategies, limits)
│   ├── synthesizer/
│   │   ├── kotlin.py           # real app.morphe.patcher code generation
│   │   └── patch_writer.py     # template clone, Gradle build, honest fallback
│   └── adapters/               # Apktool + JADX bridges (optional tools)
├── docs/
├── tests/
└── pyproject.toml
```

The analysis engine has **no third-party dependency**: DEX and AXML are parsed directly, which is why a 43 000-method APK is analysed in about 1.7 seconds and a 342 000-method one in about 9 seconds for a single goal (about 17 s for every goal). The extra honesty passes — preference-key tracing and fingerprint uniqueness — reuse the method bodies decoded during the scan, so they add no second pass.

---

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

The test suite covers the verifier (including rejection of the old ReVanced API), the Kotlin renderer, plan naming/confidence/de-duplication, camelCase token matching, the objective catalogue, the call graph, preference-key tracing, fingerprint uniqueness, split bundles and the writer, with no APK, JDK or network required.

---

## Legal

Morphy Patches Creator is provided for **personal customisation, interoperability research and education**. You are responsible for respecting the terms of service of the apps you modify and the laws of your country. Do not use it to redistribute paid content or to bypass protections you do not own.

The tool integrates with, and generates code for, the [Morphe](https://github.com/MorpheApp) ecosystem. Apktool and JADX remain the property of their authors. See [docs/CREDITS.md](docs/CREDITS.md) and [docs/LEGAL.md](docs/LEGAL.md).

---

## Credits

- [Morphe Patcher](https://github.com/MorpheApp/morphe-patcher) and [morphe-patches-template](https://github.com/MorpheApp/morphe-patches-template) — the patch API and build toolchain this project targets.
- [Apktool](https://github.com/iBotPeaches/Apktool) by Connor Tumbleson & Ryszard Wiśniewski — optional decompilation.
- [JADX](https://github.com/skylot/jadx) by @skylot — optional Java view.
- [Rich](https://github.com/Textualize/rich) and [Click](https://click.palletsprojects.com/) — the terminal experience.

Licensed under the Apache License 2.0. See [LICENSE](LICENSE).
