"""
Morphy Patches Creator - Model Context Protocol (MCP) server.

Exposes the real analysis/generation engine to AI assistants:

* ``morphy_inspect_apk``      - what is patchable in this app, and why,
* ``morphy_create_patch``     - analyse + generate patch sources + bundle,
* ``morphy_list_goals``       - the supported objectives,
* ``morphy_xrefs``            - callers / callees of an app method,
* ``morphy_search_strings``   - methods that contain a text constant,
* ``morphy_preferences``      - entitlement-like preference keys and getters,
* ``morphy_class_details``    - structural view of one class,
* ``morphy_investigate``      - evidence dossier for a goal,
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
from morphy_creator.core.apk import ApkContainer
from morphy_creator.core.plan import dedupe_plans, plans_for_report
from morphy_creator.core.preferences import PreferenceIndex
from morphy_creator.core.verifier import PatchVerifier
from morphy_creator.core.xrefs import CallGraph
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
        "name": "morphy_xrefs",
        "description": (
            "Call graph over the app's own methods: who calls a method, and what it "
            "calls. Accepts a full reference (Lcom/foo/Bar;->a()Z) or a name fragment. "
            "Use it to follow obfuscated chains (activity -> a() -> preferences)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string"},
                "method": {"type": "string", "description": "Full method reference or name fragment"},
                "direction": {
                    "type": "string",
                    "enum": ["both", "callers", "callees"],
                    "description": "Which side of the edge to return (default: both).",
                },
                "include_overrides": {
                    "type": "boolean",
                    "description": (
                        "Follow interface/override methods sharing the signature "
                        "(default: false; ignored for obfuscated names)."
                    ),
                },
            },
            "required": ["apk_path", "method"],
        },
    },
    {
        "name": "morphy_search_strings",
        "description": (
            "Searches the app's string constants and returns the methods that contain "
            "them. This is how a UI message, a preference key or a SKU is traced back "
            "to the code that reads it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string"},
                "query": {"type": "string", "description": "Text to look for (case-insensitive)"},
                "case_sensitive": {"type": "boolean"},
                "limit": {"type": "integer", "description": "Maximum methods returned (default 40)"},
            },
            "required": ["apk_path", "query"],
        },
    },
    {
        "name": "morphy_preferences",
        "description": (
            "Lists preference keys that look like entitlements (KEY_PREMIUM, is_premium, "
            "...), the methods that reference them, and the parameterless getters in the "
            "classes that own them. Works on obfuscated apps where method names are useless."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string"},
                "query": {"type": "string", "description": "Only keep keys containing this text"},
                "limit": {"type": "integer", "description": "Maximum getters returned (default 40)"},
            },
            "required": ["apk_path"],
        },
    },
    {
        "name": "morphy_class_details",
        "description": (
            "Structural view of one class: method signatures, the strings each method "
            "uses, the calls it makes and the fields it touches. Use it to read an "
            "obfuscated class before choosing a target. This is not Java source; use "
            "morphe_decompile_java for that."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string"},
                "class_name": {
                    "type": "string",
                    "description": "DEX descriptor (Lcom/foo/Bar;) or a class-name fragment",
                },
                "limit": {"type": "integer", "description": "Maximum classes returned (default 3)"},
            },
            "required": ["apk_path", "class_name"],
        },
    },
    {
        "name": "morphy_investigate",
        "description": (
            "Evidence dossier for a goal: for each candidate, the preference keys, "
            "strings, literals, callers and callees that justify it. A candidate with "
            "no hard evidence is marked 'weak' and is not recommended. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "apk_path": {"type": "string"},
                "goal": {"type": "string", "description": "Plain-language goal"},
                "objectives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit goal ids (optional, overrides goal matching)",
                },
                "with_call_graph": {
                    "type": "boolean",
                    "description": "Include callers/callees (default true; slower)",
                },
                "max_candidates": {"type": "integer", "description": "Per goal (default 4)"},
            },
            "required": ["apk_path", "goal"],
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

    if name == "morphy_xrefs":
        container = ApkContainer.open(Path(arguments["apk_path"]))
        try:
            graph = CallGraph.build(container.dex_files())
        finally:
            container.close()

        query = str(arguments["method"])
        targets = [query] if "->" in query else graph.find(query, limit=5)
        if not targets:
            return {
                "query": query,
                "error": "No method of this APK matches. Try a name fragment such as 'onResume'.",
            }

        direction = arguments.get("direction") or "both"
        include_overrides = bool(arguments.get("include_overrides", False))
        methods: List[Dict[str, Any]] = []
        for target in targets:
            entry: Dict[str, Any] = {
                "method": target,
                "declared_in_apk": graph.is_declared(target),
                "implementations": graph.implementations(target)[:10],
            }
            if direction in ("both", "callers"):
                entry["callers"] = graph.callers(target, include_overrides)[:40]
            if direction in ("both", "callees"):
                entry["callees"] = graph.callees(target)[:40]
            methods.append(entry)

        return {
            "query": query,
            "methods": methods,
            "scanned_methods": graph.method_count,
            "indexed_edges": graph.edge_count,
        }

    if name == "morphy_search_strings":
        query = str(arguments["query"])
        case_sensitive = bool(arguments.get("case_sensitive", False))
        limit = int(arguments.get("limit", 40))
        needle = query if case_sensitive else query.lower()

        container = ApkContainer.open(Path(arguments["apk_path"]))
        try:
            matches: List[Dict[str, Any]] = []
            total = 0
            for dex in container.dex_files():
                for method in dex.iter_methods():
                    if not method.has_body:
                        continue
                    code = method.code()
                    if code is None:
                        continue
                    if case_sensitive:
                        hits = [text for text in code.strings if needle in text]
                    else:
                        hits = [text for text in code.strings if needle in text.lower()]
                    if not hits:
                        continue
                    total += 1
                    if len(matches) < limit:
                        matches.append(
                            {
                                "method": method.full_name,
                                "class": method.java_class,
                                "name": method.name,
                                "descriptor": method.descriptor,
                                "strings": hits[:4],
                            }
                        )
        finally:
            container.close()

        return {"query": query, "total_matching_methods": total, "matches": matches}

    if name == "morphy_preferences":
        query = str(arguments.get("query") or "").lower()
        limit = int(arguments.get("limit", 40))
        container = ApkContainer.open(Path(arguments["apk_path"]))
        try:
            index = PreferenceIndex.build(container.dex_files())
        finally:
            container.close()

        data = index.to_dict()
        all_keys: List[Dict[str, Any]] = list(data["keys"])  # type: ignore[arg-type]
        keys = [
            entry for entry in all_keys
            if not query or query in str(entry["key"]).lower()
        ]
        getters = [
            entry for entry in index.candidate_getters()
            if not query or any(query in str(key).lower() for key in entry["keys"])
        ]
        return {
            "key_count": len(keys),
            "keys": keys[:limit],
            "candidate_getters": getters[:limit],
        }

    if name == "morphy_class_details":
        query = str(arguments["class_name"]).strip()
        limit = int(arguments.get("limit", 3))
        exact_descriptor = query if query.startswith("L") and query.endswith(";") else ""
        needle = query.lower().replace(".", "/")

        container = ApkContainer.open(Path(arguments["apk_path"]))
        try:
            found: List[Dict[str, Any]] = []
            for dex in container.dex_files():
                for cls in dex.classes:
                    if exact_descriptor:
                        matches = cls.descriptor == exact_descriptor
                    else:
                        matches = needle in cls.descriptor.lower() or needle in cls.java_name.lower()
                    if not matches:
                        continue

                    methods: List[Dict[str, Any]] = []
                    for method in cls.methods[:80]:
                        code = method.code() if method.has_body else None
                        methods.append(
                            {
                                "name": method.name,
                                "descriptor": method.descriptor,
                                "return_type": method.return_type,
                                "access_flags": f"0x{method.access_flags:04x}",
                                "static": method.is_static,
                                "has_body": method.has_body,
                                "strings": (code.strings[:6] if code else []),
                                "calls": (code.called_methods[:6] if code else []),
                                "fields": ([name for (_op, name, _type) in code.field_accesses[:6]]
                                           if code else []),
                            }
                        )
                    found.append(
                        {
                            "descriptor": cls.descriptor,
                            "java_name": cls.java_name,
                            "super": cls.super_descriptor,
                            "source_file": cls.source_file,
                            "method_count": len(cls.methods),
                            "methods": methods,
                        }
                    )
                    if len(found) >= limit:
                        break
                if len(found) >= limit:
                    break
        finally:
            container.close()

        if not found:
            return {
                "query": query,
                "error": (
                    "No class matches. Use a descriptor such as Lcom/foo/Bar; "
                    "or a package fragment such as com/foo."
                ),
            }
        return {"query": query, "classes": found}

    if name == "morphy_investigate":
        from morphy_creator.core.investigate import investigate as run_investigation

        goal = str(arguments["goal"])
        objectives = [
            OBJECTIVES_BY_ID[str(item)]
            for item in (arguments.get("objectives") or [])
            if str(item) in OBJECTIVES_BY_ID
        ]
        if not objectives:
            objectives = match_text(goal)
        if not objectives:
            keywords = [word for word in goal.replace(",", " ").split() if len(word) > 3]
            if not keywords:
                return {"goal": goal, "error": "No keywords to investigate."}
            objectives = [custom_objective(keywords)]

        return run_investigation(
            Path(arguments["apk_path"]),
            objectives,
            with_call_graph=bool(arguments.get("with_call_graph", True)),
            max_candidates=int(arguments.get("max_candidates", 4)),
        )

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
                        "serverInfo": {"name": "morphy-mcp", "version": "2.1.0"},
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
