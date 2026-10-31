"""
Morphy Patches Creator - Model Context Protocol (MCP) Server
Enables AI Agents (Claude Code, Antigravity, Cursor, Codex, Windsurf)
to autonomously reverse engineer APKs, inspect binaries, synthesize Kotlin patches,
and build .mpp bundles without requiring separate API keys.
"""
import sys
import json
import logging
from pathlib import Path
from morphy_creator.core.pipeline import PatchWorkbenchPipeline
from morphy_creator.adapters.apktool_adapter import ApktoolAdapter
from morphy_creator.adapters.jadx_adapter import JadxAdapter
from morphy_creator.adapters.androguard_adapter import AndroguardAdapter
from morphy_creator.adapters.rea_adapter import ReaAdapter
from morphy_creator.synthesizer.patch_template_engine import PatchTemplateEngine

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("morphy.mcp")

TOOLS = [
    {
        "name": "morphe_unpack_apk",
        "description": "Unpacks an APK or split APKM bundle into resources, decoded AndroidManifest.xml, and Smali bytecode via Apktool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string", "description": "Absolute or relative path to the APK/APKM file"},
                "output_dir": {"type": "string", "description": "Destination directory for unpacked assets"}
            },
            "required": ["apk_path", "output_dir"]
        }
    },
    {
        "name": "morphe_decompile_java",
        "description": "Decompiles APK bytecode into readable high-level Java source code via JADX for AI semantic reasoning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string", "description": "Path to the APK file"},
                "output_dir": {"type": "string", "description": "Directory to save decompiled Java sources"}
            },
            "required": ["apk_path", "output_dir"]
        }
    },
    {
        "name": "morphe_scan_semantics",
        "description": "Fast pure-Python semantic scan using Androguard to find classes, methods, and strings matching target feature keywords.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string", "description": "Path to the APK file"},
                "keywords": {"type": "array", "items": {"type": "string"}, "description": "Keywords to search (e.g. ['isPremium', 'showAd', 'FLAG_SECURE'])"}
            },
            "required": ["apk_path", "keywords"]
        }
    },
    {
        "name": "morphe_inspect_native",
        "description": "Deep-scans native .so shared libraries, JNI export tables, and call graph cross-references via REA.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lib_dir": {"type": "string", "description": "Path to the extracted lib/ directory containing .so files"}
            },
            "required": ["lib_dir"]
        }
    },
    {
        "name": "morphe_synthesize_patch",
        "description": "Synthesizes an idiomatic Morphe Kotlin patch class with resilient opcode/string fingerprints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_name": {"type": "string", "description": "Target package name identifier (e.g. 'custom')"},
                "patch_name": {"type": "string", "description": "Human-readable patch title"},
                "class_name": {"type": "string", "description": "Kotlin object class name (e.g. 'AdBlockPatch')"},
                "description": {"type": "string", "description": "Patch description"},
                "strings": {"type": "array", "items": {"type": "string"}, "description": "Fingerprint anchor strings"},
                "opcodes": {"type": "array", "items": {"type": "string"}, "description": "Fingerprint Dalvik opcodes"},
                "output_file": {"type": "string", "description": "Destination file path for the .kt patch"}
            },
            "required": ["package_name", "patch_name", "class_name", "description", "strings", "opcodes", "output_file"]
        }
    },
    {
        "name": "morphe_build_bundle",
        "description": "Assembles and compiles synthesized Kotlin patches into a distribution-ready .mpp Morphe bundle.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "patches_dir": {"type": "string", "description": "Directory containing synthesized .kt patches"},
                "output_mpp": {"type": "string", "description": "Destination file path for the compiled .mpp bundle"}
            },
            "required": ["patches_dir", "output_mpp"]
        }
    }
]

def handle_call_tool(name: str, arguments: dict) -> dict:
    pipeline = PatchWorkbenchPipeline()

    if name == "morphe_unpack_apk":
        apk_path = Path(arguments["apk_path"])
        output_dir = Path(arguments["output_dir"])
        adapter = ApktoolAdapter()
        success = adapter.decode(apk_path, output_dir)
        return {"status": "success" if success else "fallback", "path": str(output_dir)}

    elif name == "morphe_decompile_java":
        apk_path = Path(arguments["apk_path"])
        output_dir = Path(arguments["output_dir"])
        adapter = JadxAdapter()
        success = adapter.decompile(apk_path, output_dir)
        return {"status": "success" if success else "pending", "path": str(output_dir)}

    elif name == "morphe_scan_semantics":
        apk_path = Path(arguments["apk_path"])
        keywords = arguments.get("keywords", [])
        adapter = AndroguardAdapter()
        findings = adapter.scan_apk_semantics(apk_path, keywords)
        return {"status": "success", "findings": findings}

    elif name == "morphe_inspect_native":
        lib_dir = Path(arguments["lib_dir"])
        adapter = ReaAdapter()
        findings = adapter.scan_native_binaries(lib_dir)
        return {"status": "success", "native_findings": findings}

    elif name == "morphe_synthesize_patch":
        code = PatchTemplateEngine.render_unlock_patch(
            package_name=arguments["package_name"],
            patch_name=arguments["patch_name"],
            class_name=arguments["class_name"],
            description=arguments["description"],
            strings=arguments["strings"],
            opcodes=arguments["opcodes"]
        )
        out_file = Path(arguments["output_file"])
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(code, encoding="utf-8")
        return {"status": "success", "patch_path": str(out_file), "preview": code[:200] + "..."}

    elif name == "morphe_build_bundle":
        patches_dir = Path(arguments["patches_dir"])
        output_mpp = Path(arguments["output_mpp"])
        res = pipeline.build_bundle(patches_dir, output_mpp)
        return {"status": "success", "bundle_path": str(res)}

    return {"error": f"Unknown tool: {name}"}

def run_stdio_server():
    """Standard JSON-RPC Stdio server conforming to the Model Context Protocol."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")

            if method == "tools/list":
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
            elif method == "tools/call":
                params = req.get("params", {})
                res = handle_call_tool(params.get("name"), params.get("arguments", {}))
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(res, indent=2)}]}}
            elif method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "morphy-mcp", "version": "1.0.0"},
                        "capabilities": {"tools": {}}
                    }
                }
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            err_resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}}
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    run_stdio_server()
