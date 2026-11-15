"""
Cross-references (call graph) for the app's own DEX methods.

The heuristic scorer answers "does this method *look* like the feature?". A
call graph answers the next question: "who reaches this method, and what does
it call?". That is what lets an investigator follow an obfuscated chain such
as ``PremiumActivity.onResume -> az4.a -> rd5.e -> SharedPreferences``.

The graph is built on demand (MCP tool or the future agent loop), never during
the normal scan, so it does not slow the wizard down. Only calls that resolve
to a method *declared in the APK* are indexed: framework calls would triple the
memory for no investigative value.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# A method reference as it appears in bytecode: ``Lcom/foo/Bar;->a()Z``.
@dataclass(frozen=True)
class MethodRef:
    class_descriptor: str
    name: str
    descriptor: str

    @property
    def full_name(self) -> str:
        return f"{self.class_descriptor}->{self.name}{self.descriptor}"

    @property
    def signature(self) -> str:
        """Name + descriptor: shared by overrides and interface implementations."""
        return f"{self.name}{self.descriptor}"

    @classmethod
    def parse(cls, text: str) -> "MethodRef":
        arrow = text.find("->")
        if arrow <= 0:
            raise ValueError(f"Not a method reference: {text!r}")
        class_descriptor = text[:arrow]
        rest = text[arrow + 2:]
        paren = rest.find("(")
        name = rest if paren == -1 else rest[:paren]
        descriptor = "" if paren == -1 else rest[paren:]
        return cls(class_descriptor=class_descriptor, name=name, descriptor=descriptor)


class CallGraph:
    """Reverse and forward call index over the APK's own methods."""

    def __init__(self) -> None:
        self._callers: Dict[str, List[str]] = {}
        self._callees: Dict[str, List[str]] = {}
        # Every call-site reference seen, grouped by ``name(descriptor)``, so an
        # interface/override method can be followed even when the call was
        # compiled against a different declaring class.
        self._called_by_signature: Dict[str, Set[str]] = {}
        self._declared: List[str] = []
        self._declared_set: Set[str] = set()
        self._signature_to_declared: Dict[str, List[str]] = {}
        self.edge_count = 0

    # -- construction -----------------------------------------------------------
    @classmethod
    def build(cls, dex_files: Iterable[object], release: bool = True) -> "CallGraph":
        graph = cls()
        declared: Set[str] = set()

        for dex in dex_files:
            for method in dex.iter_methods():  # type: ignore[attr-defined]
                if not method.has_body:  # type: ignore[attr-defined]
                    continue
                full_name = method.full_name  # type: ignore[attr-defined]
                declared.add(full_name)
                graph._declared.append(full_name)
                graph._declared_set.add(full_name)
                try:
                    ref = MethodRef.parse(full_name)
                except ValueError:
                    continue
                graph._signature_to_declared.setdefault(ref.signature, []).append(full_name)

                code = method.code()  # type: ignore[attr-defined]
                if code is not None:
                    callees = list(dict.fromkeys(code.called_methods))
                    if callees:
                        graph._callees[full_name] = callees
                if release:
                    # Do not keep decoded bodies alive: the graph only needs names.
                    method._code = None  # type: ignore[attr-defined]

        # Second pass over the already-decoded call lists: index only edges that
        # land on a method declared in this APK.
        for caller, callees in graph._callees.items():
            for callee in callees:
                if callee not in declared:
                    continue
                graph._callers.setdefault(callee, []).append(caller)
                graph.edge_count += 1
                try:
                    ref = MethodRef.parse(callee)
                except ValueError:
                    continue
                graph._called_by_signature.setdefault(ref.signature, set()).add(callee)

        return graph

    # -- queries ----------------------------------------------------------------
    @property
    def method_count(self) -> int:
        return len(self._declared)

    def callers(self, target: str, include_overrides: bool = False) -> List[str]:
        """Methods that call ``target`` (exact, plus same-signature calls)."""
        names: Set[str] = {target}
        if include_overrides:
            try:
                ref = MethodRef.parse(target)
            except ValueError:
                ref = None
            # Grouping by signature is meaningless for R8 names such as ``a``:
            # it would merge every unrelated ``a()Z`` in the app.
            if ref is not None and len(ref.name) > 2:
                names |= self._called_by_signature.get(ref.signature, set())
        seen: Set[str] = set()
        result: List[str] = []
        for name in names:
            for caller in self._callers.get(name, ()):
                if caller not in seen:
                    seen.add(caller)
                    result.append(caller)
        return result

    def callees(self, method: str) -> List[str]:
        return list(self._callees.get(method, ()))

    def is_declared(self, method: str) -> bool:
        return method in self._declared_set

    def implementations(self, method: str) -> List[str]:
        """Declared methods sharing the name + descriptor (overrides, interfaces)."""
        try:
            ref = MethodRef.parse(method)
        except ValueError:
            return []
        if len(ref.name) <= 2:
            # An obfuscated ``a()Z`` is not an override; it is a coincidence.
            return []
        return list(self._signature_to_declared.get(ref.signature, ()))

    def find(self, needle: str, limit: int = 20) -> List[str]:
        """Declared methods whose full name contains ``needle`` (case-insensitive)."""
        wanted = (needle or "").lower()
        if not wanted:
            return []
        found: List[str] = []
        for full_name in self._declared:
            if wanted in full_name.lower():
                found.append(full_name)
                if len(found) >= limit:
                    break
        return found

    def describe(self, method: str) -> Optional[Dict[str, object]]:
        try:
            ref = MethodRef.parse(method)
        except ValueError:
            return None
        return {
            "full_name": ref.full_name,
            "class": ref.class_descriptor,
            "method": ref.name,
            "descriptor": ref.descriptor,
            "declared_in_apk": method in self._declared_set,
            "callees": self.callees(method)[:20],
            "callers": self.callers(method)[:20],
        }


def caller_tree(graph: CallGraph, target: str, depth: int = 2, max_nodes: int = 60) -> List[Dict[str, object]]:
    """Breadth-first list of callers, for the investigator's evidence trail."""
    seen: Set[str] = set()
    frontier: List[Tuple[str, int]] = [(target, 0)]
    trail: List[Dict[str, object]] = []
    while frontier and len(trail) < max_nodes:
        method, level = frontier.pop(0)
        if method in seen:
            continue
        seen.add(method)
        callers = graph.callers(method)
        trail.append({"method": method, "depth": level, "callers": callers[:10]})
        if level + 1 <= depth:
            for caller in callers:
                if caller not in seen:
                    frontier.append((caller, level + 1))
    return trail
