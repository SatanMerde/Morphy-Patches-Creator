"""
Kotlin code generation for Morphe patches.

The generated code targets the current Morphe Patcher API (``app.morphe.*``):

* a patch is a public top-level ``val`` created by ``patch(...)`` - there is no
  ``@Patch`` annotation and no ``replaceMethod`` in this API,
* fingerprints are ``Fingerprint`` objects matched with ``match()``,
* behaviour is changed with ``returnEarly(...)`` or, for blocking flags, by
  replacing the literal instruction itself.

Everything emitted here is plain, readable Kotlin: a non-technical user can
still recognise the description and the "why" comments.
"""
from __future__ import annotations

import re
from typing import List

from morphy_creator.core.plan import PatchPlan, PatchStep
from morphy_creator.presets.objectives import (
    STRATEGY_BOOLEAN_FALSE,
    STRATEGY_BOOLEAN_TRUE,
    STRATEGY_CLEAR_BODY,
    STRATEGY_DROP_FLAG,
    STRATEGY_RETURN_VOID,
    STRATEGY_RETURN_ZERO,
)

# DEX const opcodes -> smali instruction used to replace the same literal.
_CONST_SMALI = {
    0x12: "const/4 v{reg}, 0x0",
    0x13: "const/16 v{reg}, 0x0",
    0x14: "const v{reg}, 0x0",
    0x15: "const/high16 v{reg}, 0x0",
}


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )


def _val_name(plan: PatchPlan) -> str:
    name = plan.class_name[:1].lower() + plan.class_name[1:]
    return name if name.endswith("Patch") else name + "Patch"


def _identifier(text: str) -> str:
    """Turns any method name into a legal Kotlin identifier fragment.

    ``access$getHasSubscriptionUpgradeHint`` contains ``$``, which is reserved
    for string templates in Kotlin and cannot appear in an identifier.
    """
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_")
    return cleaned or "Target"


def _fingerprint_name(step: PatchStep, index: int) -> str:
    base = _identifier(step.target.method_name.lstrip("_"))
    if "_" in base:
        # snake_case / sanitized names: build PascalCase word by word.
        base = "".join(part[:1].upper() + part[1:] for part in base.split("_") if part)
    if not base or base[0].isdigit():
        base = f"Target{index}"
    return f"{base[:1].lower() + base[1:]}Fingerprint"


def _fingerprint_names(plan: PatchPlan) -> List[str]:
    """Fingerprint object names, made unique (overloads share a method name)."""
    names: List[str] = []
    used: set = set()
    for index, step in enumerate(plan.steps, start=1):
        candidate = _fingerprint_name(step, index)
        if candidate in used:
            stem = candidate[: -len("Fingerprint")]
            suffix = 2
            while f"{stem}{suffix}Fingerprint" in used:
                suffix += 1
            candidate = f"{stem}{suffix}Fingerprint"
        used.add(candidate)
        names.append(candidate)
    return names


def _return_expression(step: PatchStep) -> str:
    """Kotlin argument for ``returnEarly(...)`` depending on the return type."""
    return_type = step.target.return_type
    strategy = step.strategy

    if strategy in (STRATEGY_BOOLEAN_TRUE, STRATEGY_BOOLEAN_FALSE):
        return "true" if strategy == STRATEGY_BOOLEAN_TRUE else "false"
    if strategy in (STRATEGY_RETURN_VOID, STRATEGY_CLEAR_BODY):
        return ""  # returnEarly() with no argument
    if return_type == "V":
        return ""
    if return_type == "J":
        return "0L"
    if return_type in ("F", "D"):
        return "0.0"
    if return_type == "Ljava/lang/String;":
        return '""'
    return "0"


def _fingerprint_block(step: PatchStep, name: str) -> str:
    target = step.target
    lines: List[str] = [f"private object {name} : Fingerprint("]
    lines.append(f'    definingClass = "{_escape(target.class_descriptor)}",')
    lines.append(f'    name = "{_escape(target.method_name)}",')
    lines.append(f'    returnType = "{_escape(target.return_type)}",')

    parameters = _parameters_of(target.method_descriptor)
    joined = ", ".join(f'"{_escape(p)}"' for p in parameters)
    lines.append(f"    parameters = listOf({joined}),")

    anchors = [text for text in target.strings if text and len(text) >= 3][:3]
    if anchors:
        joined_strings = ", ".join(f'"{_escape(text)}"' for text in anchors)
        lines.append(f"    strings = listOf({joined_strings}),")

    if step.strategy == STRATEGY_DROP_FLAG:
        for literal in target.literals[:1]:
            lines.append(f"    filters = listOf(literal({literal})),")

    lines.append(")")
    return "\n".join(lines)


def _parameters_of(descriptor: str) -> List[str]:
    """``(I Ljava/lang/String;)V`` -> ``["I", "Ljava/lang/String;"]``."""
    if not descriptor.startswith("("):
        return []
    inner = descriptor[1:descriptor.find(")")]
    params: List[str] = []
    index = 0
    while index < len(inner):
        char = inner[index]
        if char == "[":
            start = index
            while index < len(inner) and inner[index] == "[":
                index += 1
            if index < len(inner) and inner[index] == "L":
                end = inner.find(";", index)
                index = (end + 1) if end != -1 else index + 1
            else:
                index += 1
            params.append(inner[start:index])
        elif char == "L":
            end = inner.find(";", index)
            if end == -1:
                break
            params.append(inner[index:end + 1])
            index = end + 1
        else:
            params.append(char)
            index += 1
    return params


def _execute_block(plan: PatchPlan, names: List[str]) -> str:
    lines: List[str] = ["    execute {"]
    for index, (step, fingerprint) in enumerate(zip(plan.steps, names), start=1):

        if step.strategy == STRATEGY_DROP_FLAG and step.target.literal_sites:
            opcode, register, _value = step.target.literal_sites[0]
            smali = _CONST_SMALI.get(opcode, "const/16 v{reg}, 0x0").format(reg=register)
            lines.append(f"        // {step.target.signature}: stop setting the blocking flag")
            lines.append(f"        val target{index} = {fingerprint}.match()")
            lines.append(f"        val index{index} = target{index}.instructionMatches.first().index")
            lines.append(
                f'        target{index}.method.replaceInstruction(index{index}, "{smali}")'
            )
        else:
            argument = _return_expression(step)
            call = f"{fingerprint}.match().method.returnEarly({argument})" if argument \
                else f"{fingerprint}.match().method.returnEarly()"
            lines.append(f"        // {step.target.signature}")
            lines.append(f"        {call}")

    lines.append("    }")
    return "\n".join(lines)


def render(plan: PatchPlan) -> str:
    """Renders one complete Kotlin patch file."""
    val_name = _val_name(plan)
    fingerprint_names = _fingerprint_names(plan)
    uses_match = True
    uses_replace = any(step.strategy == STRATEGY_DROP_FLAG and step.target.literal_sites
                       for step in plan.steps)
    uses_literal = uses_replace
    uses_return_early = any(
        not (step.strategy == STRATEGY_DROP_FLAG and step.target.literal_sites)
        for step in plan.steps
    )

    header = [
        "/*",
        f" * {plan.title}",
        f" * App: {plan.app_package} {plan.app_version}".rstrip(),
        " *",
        " * Generated by Morphy Patches Creator. Each target below was found by",
        " * static analysis of the app, not guessed.",
        " *",
    ]
    for step in plan.steps:
        header.append(f" * - {step.target.signature}: {step.plain_action}")
        for reason in step.target.reasons[:2]:
            header.append(f" *     {reason}")
    header.append(" */")

    imports = [
        "import app.morphe.patcher.Fingerprint",
    ]
    if uses_literal:
        imports.append("import app.morphe.patcher.literal")
    if uses_match:
        imports.append("import app.morphe.patcher.match")
    if uses_replace:
        imports.append("import app.morphe.patcher.extensions.InstructionExtensions.replaceInstruction")
        imports.append("import app.morphe.patcher.instructionMatches")
    if uses_return_early:
        imports.append("import app.morphe.patcher.util.returnEarly")
    imports.append("import app.morphe.patcher.patch.Compatibility")
    imports.append("import app.morphe.patcher.patch.patch")

    body = [
        "",
        '@Suppress("unused")',
        f"val {val_name} = patch(",
        f'    name = "{_escape(plan.title)}",',
        f'    description = "{_escape(plan.description)}",',
        "    default = true,",
        ") {",
    ]

    if plan.app_package:
        app_name = plan.app_package.rsplit(".", 1)[-1]
        body.append(
            f'    compatibleWith(Compatibility("{_escape(plan.app_package)}", '
            f'"{_escape(app_name)}"))'
        )

    body.append(_execute_block(plan, fingerprint_names))
    body.append("}")
    body.append("")

    for step, name in zip(plan.steps, fingerprint_names):
        body.append(_fingerprint_block(step, name))
        body.append("")

    return "\n".join(
        header
        + [""]
        + [f"package app.morphe.patches.{plan.package_name}"]
        + [""]
        + imports
        + body
    ).rstrip() + "\n"
