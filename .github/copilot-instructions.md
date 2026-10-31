# GitHub Copilot & Codex Instructions for Morphy Patches Creator

## Project Overview
Morphy Patches Creator is an agentic engineering workbench for reverse engineering Android apps and generating resilient Kotlin bytecode patches for the Morphe ecosystem.

## Key Directives
- **Zero-Code Operation**: Enable end-users to achieve their goals by running automated pipelines (`morphy-creator auto` or through the MCP server).
- **Morphe API Conformance**:
  - Extend `BytecodePatch` with `@Patch(name = "...", description = "...", version = "...")`.
  - Use `Fingerprint` objects for robust method matching across app updates.
  - Apply method overrides with `match.method.replaceMethod { instructions = "..." }`.
- **Architecture**:
  - `Apktool`: Smali, Manifest, and resource extraction.
  - `REA`: Native `.so` libraries, JNI boundaries, and xref tracing.
  - `JADX`: High-level Java decompilation.
  - `Androguard`: Static CFG and string extraction.
  - `Morphe-AI`: Automated AST patch synthesis.
