# Morphy Patches Creator - Claude Code Agent Guide

This repository is an AI-native workbench for reverse engineering Android applications and synthesizing production-ready Kotlin patches for the **Morphe Patcher** ecosystem (`.mpp`).

## Your Role as the Patching Agent
When the user asks to analyze an APK or create a patch:
1. **Unpack & Decompile**: Use `morphy-creator unpack <app.apk> -o ./workspace` (Apktool) and inspect high-level Java sources via JADX (`morphy-creator inspect`).
2. **Locate Target Logic**: Search for semantic feature gates, boolean flags, or license verification routines matching the user's intent.
3. **Synthesize Resilient Patch**: Create an idiomatic Morphe Kotlin patch inheriting from `BytecodePatch`, using opcode & string `Fingerprint` definitions that survive ProGuard/R8 obfuscation.
4. **Compile Bundle**: Run `morphy-creator build ./patches -o ./dist/patches.mpp` to provide a ready-to-load bundle for Morphe Manager.

## Architectural Toolchain
- **Apktool**: Binary XML decoding, Smali extraction, resource IDs (`resources.arsc`).
- **REA**: Native `.so` libraries, JNI boundaries, call graph cross-references.
- **JADX**: High-level Java decompilation for semantic comprehension.
- **Androguard**: Rapid Python-native static control flow analysis.
- **Morphe-AI**: Automated AST bytecode manipulation and resilient fingerprinting.

## MCP Server Connection (Claude Desktop / Claude Code)
To connect Morphy's MCP server directly into Claude:
```json
{
  "mcpServers": {
    "morphy": {
      "command": "python",
      "args": ["-m", "morphy_creator.mcp_server"]
    }
  }
}
```
