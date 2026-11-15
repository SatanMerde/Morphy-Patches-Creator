# GitHub Copilot & Codex instructions — Morphy Patches Creator

## Project

A guided, zero-code tool that turns a plain-English goal into a Morphe patch. It parses APK bytecode natively (no Androguard), ranks hook candidates with evidence, emits current-API Kotlin, and compiles a `.mpp` when the toolchain is available.

## Directives

- **Zero-code first.** The default command is a wizard. Keep messages free of jargon and always explain *why* a method was picked.
- **Real data only.** Never invent methods, strings or scores.
- **Morphe API conformance.** A patch is `val name = patch(name = "...", description = "...") { execute { ... } }`. Use `Fingerprint(...)` + `.match()`, `returnEarly(...)`, `replaceInstruction(...)`, and `compatibleWith(Compatibility(...))`. Do **not** use `@Patch`, `BytecodePatch`, `resourcePatch`, or `replaceMethod`: they do not exist in the current API.
- **Honest packaging.** An `.mpp` must contain `classes.dex` produced by D8 (`:patches:buildAndroid`). Without Java, Git and a GitHub `read:packages` token, return `dist/morphy-project.zip` and setup steps.

## Modules

| Module | Responsibility |
|---|---|
| `core/dex.py`, `core/axml.py` | dependency-free DEX / binary-XML readers |
| `core/apk.py` | container facts, packers, native libs |
| `core/analysis.py`, `presets/objectives.py` | real scoring engine and goal catalogue |
| `core/plan.py` | plans, confidence, de-duplication |
| `synthesizer/kotlin.py`, `synthesizer/patch_writer.py` | code generation and packaging |
| `core/verifier.py` | API and structural checks |
| `mcp_server.py` | six MCP tools |

Tests: `python -m pytest tests -q`.
