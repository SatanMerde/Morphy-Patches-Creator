# Morphy Patches Creator — agent guide

This repository builds Morphe patches (`.mpp`) for Android apps. The primary user is **not a developer**: the default entry point is a guided wizard.

## What the pipeline really does

1. `core/apk.py` opens the APK and reads `AndroidManifest.xml` (hand-written AXML parser), lists DEX files and native libraries.
2. `core/dex.py` decodes every method: string constants, called methods, integer literals and their `(opcode, register, value)` sites.
3. `core/analysis.py` + `presets/objectives.py` score methods against the requested goals. A candidate needs a primary signal (name token, SDK call, blocking literal). No mock data, no network.
4. `core/plan.py` turns findings into `PatchPlan`s (plain-English actions, confidence, de-duplication).
5. `synthesizer/kotlin.py` emits Kotlin for the **current** `app.morphe.patcher` API.
6. `core/verifier.py` rejects stale API and weak fingerprints.
7. `synthesizer/patch_writer.py` copies sources into `MorpheApp/morphe-patches-template` and runs `:patches:buildAndroid` when Java + Git + registry token exist. Otherwise it returns a buildable project archive and says so.

## Non-negotiable rules

- **Do not invent analysis results.** If you change scoring, run it on a real APK and report what it found.
- **Do not fake a bundle.** `kind="mpp"` is only valid after a successful `buildAndroid`. Never generate a `.mpp` by zipping sources.
- **Use the real API.** No `@Patch` annotation, no `BytecodePatch` base class, no `replaceMethod` — none of them exist. A patch is a public top-level `val ... = patch(...)`.
- **Keep the plain-English layer.** Every candidate must retain its `reasons`; a non-technical user approves the plan from them.
- **Stay dependency-light.** DEX/AXML parsing is pure Python on purpose. Add a dependency only if it is unavoidable.

## Commands

```bash
morphy-creator                      # wizard (default)
morphy-creator inspect app.apk --details
morphy-creator create app.apk --for ads,premium -y
morphy-creator auto  app.apk --prompt "remove ads and screenshots"
morphy-creator build <folder>
morphy-creator verify <file.kt>
morphy-creator doctor
morphy-creator mcp
```

Tests: `python -m pytest tests -q` (no APK, JDK or network needed).

## MCP server (Claude Desktop / Claude Code / OpenCode)

```json
{
  "mcpServers": {
    "morphy": {
      "command": "C:\\path\\to\\Morphy-Patches-Creator\\.venv\\Scripts\\morphy-creator.exe",
      "args": ["mcp"]
    }
  }
}
```

Tools: `morphy_list_goals`, `morphy_inspect_apk`, `morphy_create_patch`, `morphe_unpack_apk`, `morphe_decompile_java`, `morphe_build_bundle`.
