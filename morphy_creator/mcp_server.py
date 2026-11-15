"""
Morphy Patches Creator - Model Context Protocol (MCP) server.

Exposes the real analysis/generation engine to AI assistants:

* ``morphy_inspect_apk``      - what is patchable in this app, and why,
* ``morphy_create_patch``     - analyse + generate patch sources + bundle,
* ``morphy_list_goals``       - the supported objectives,
* ``morphe_unpack_apk``       - Apktool decompilation,
* ``morphe_decompile_java``   - JADX decompilation,
* ``morphe_build_bundle``     - compile the generated sources into a .mpp.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from morphy_creator.core.analysis import analyse
from morphy_creator.core.plan import dedupe_plans, plans_for_report
from morphy_creator.core.verifier import PatchVerifier
from morphy_creator.presets.objectives import OBJECTIVES, OBJECTIVES_BY_ID, custom_objective, match_text
from morphy_creator.synthesizer.patch_writer import PatchWriter

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("morphy.mcp")

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "morphy_list_goals",
        "description": "Lists the patch goals supported by Morphy (ads, premium, screenshots, ...).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "morphy_inspect_apk",
        "description": (
            "Analyses an APK without writing anything: package, version, protections, "
            "and for each goal the concrete methods that control it, with the evidence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string", "description": "Path to the .apk file"},
                "goals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Goal ids (see morphy_list_goals). Omit to analyse everything.",
                },
            },
            "required": ["apk_path"],
        },
    },
    {
        "name": "morphy_create_patch",
        "description": (
            "Full pipeline: analyse the APK, generate Morphe Kotlin patch sources, "
            "self-check them, and build a bundle when the toolchain is available."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string"},
                "goals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Goal ids, or plain words such as 'remove ads'.",
                },
                "output_dir": {"type": "string", "description": "Folder for sources, report and bundle"},
                "max_targets": {"type": "integer", "description": "Methods patched per goal (default 2)"},
            },
            "required": ["apk_path", "goals", "output_dir"],
        },
    },
    {
        "name": "morphe_unpack_apk",
        "description": "Decompiles an APK with Apktool (manifest, resources, Smali).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string"},
                "output_dir": {"type": "string"},
            },
            "required": ["apk_path", "output_dir"],
        },
    },
    {
        "name": "morphe_decompile_java",
        "description": "Decompiles an APK to Java sources with JADX.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string"},
                "output_dir": {"type": "string"},
            },
            "required": ["apk_path", "output_dir"],
        },
    },
    {
        "name": "morphe_build_bundle",
        "description": "Compiles generated .kt patches into a Morphe .mpp bundle.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "patches_dir": {"type": "string"},
                "output_dir": {"type": "string"},
            },
            "required": ["patches_dir"],
        },
    },
]


def _resolve_goals(values: List[str]):
    goals = []
    seen = set()
    for value in values or []:
        matches = []
        if value in OBJECTIVES_BY_ID:
            matches = [OBJECTIVES_BY_ID[value]]
        else:
            matches = match_text(value)
        for objective in matches:
            if objective.id not in seen:
                seen.add(objective.id)
                goals.append(objective)
    if not goals and values:
        keywords = [word for value in values for word in value.split() if len(word) > 3]
        if keywords:
            goals = [custom_objective(keywords)]
    return goals


def handle_call_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if name == "morphy_list_goals":
        return {
            "goals": [
                {"id": objective.id, "title": objective.title, "what_it_does": objective.tagline}
                for objective in OBJECTIVES
            ]
        }

    if name == "morphy_inspect_apk":
        goals = _resolve_goals(arguments.get("goals") or []) or list(OBJECTIVES)
        report = analyse(Path(arguments["apk_path"]), goals)
        return {
            "app": {
                "package": report.info.package,
                "version": report.info.version_name,
                "min_android": report.info.min_sdk,
                "protections": report.info.packers,
                "native_libraries": report.info.native_libs,
            },
            "scanned": {"methods": report.method_count, "classes": report.class_count},
            "goals": {
                finding.objective_id: {
                    "title": finding.title,
                    "summary": finding.summary(),
                    "detected_libraries": finding.detected_libraries,
                    "candidates": [candidate.to_dict() for candidate in finding.candidates],
                }
                for finding in report.findings.values()
            },
            "warnings": report.warnings,
        }

    if name == "morphy_create_patch":
        goals = _resolve_goals(arguments.get("goals") or [])
        if not goals:
            return {"error": "No goal understood. Call morphy_list_goals first."}
        output_dir = Path(arguments["output_dir"])
        report = analyse(Path(arguments["apk_path"]), goals)
        plans = dedupe_plans(
            plans_for_report(report, goals, max_steps=int(arguments.get("max_targets", 2)))
        )
        writer = PatchWriter(output_dir)
        written = [str(writer.write(plan)) for plan in plans]
        checks = [PatchVerifier.verify_patch_file(Path(path)) for path in written]
        result = writer.build_bundle([Path(path) for path in written])
        return {
            "app": report.info.package,
            "plans": [
                {
                    "goal": plan.objective_id,
                    "title": plan.title,
                    "confidence": plan.confidence,
                    "verify_hint": plan.verify_hint,
                    "limits": plan.limits,
                    "steps": [step.to_dict() for step in plan.steps],
                }
                for plan in plans
            ],
            "patch_files": written,
            "checks": checks,
            "bundle": {"kind": result.kind, "path": str(result.path), "message": result.message},
            "next_steps": result.next_steps,
            "warnings": report.warnings,
        }

    if name == "morphe_unpack_apk":
        from morphy_creator.adapters.apktool_adapter import ApktoolAdapter

        success = ApktoolAdapter().decode(Path(arguments["apk_path"]), Path(arguments["output_dir"]))
        return {"status": "success" if success else "failed", "path": arguments["output_dir"]}

    if name == "morphe_decompile_java":
        from morphy_creator.adapters.jadx_adapter import JadxAdapter

        success = JadxAdapter().decompile(Path(arguments["apk_path"]), Path(arguments["output_dir"]))
        return {"status": "success" if success else "failed", "path": arguments["output_dir"]}

    if name == "morphe_build_bundle":
        patches_dir = Path(arguments["patches_dir"])
        output_dir = Path(arguments.get("output_dir") or patches_dir)
        files = sorted(patches_dir.glob("**/*.kt"))
        if not files:
            return {"error": "No .kt file found in this folder."}
        result = PatchWriter(output_dir).build_bundle(files)
        return {
            "kind": result.kind,
            "path": str(result.path),
            "message": result.message,
            "next_steps": result.next_steps,
        }

    return {"error": f"Unknown tool: {name}"}


def run_stdio_server() -> None:
    """JSON-RPC stdio server for the Model Context Protocol."""
    for line in sys.stdin:
        if not line.strip():
            continue
        request_id = None
        try:
            request = json.loads(line)
            method = request.get("method")

            # Notifications (e.g. notifications/initialized) must not be answered.
            if "id" not in request:
                continue

            request_id = request.get("id")

            if method == "tools/list":
                response = {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
            elif method == "tools/call":
                params = request.get("params", {})
                result = handle_call_tool(params.get("name", ""), params.get("arguments", {}) or {})
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
                }
            elif method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {"name": "morphy-mcp", "version": "2.0.0"},
                        "capabilities": {"tools": {}},
                    },
                }
            else:
                response = {"jsonrpc": "2.0", "id": request_id, "result": {}}

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except Exception as exc:  # noqa: BLE001
            error = {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc)}}
            sys.stdout.write(json.dumps(error) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_server()
