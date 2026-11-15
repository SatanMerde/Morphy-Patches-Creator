"""
Minimal, dependency-free reader for Android DEX bytecode.

Only what Morphy needs is implemented:

* string / type / proto / method / class tables,
* class data (declared methods with access flags and their ``code_item`` offset),
* linear decoding of method instructions to extract
  - ``const-string`` anchors (used to build resilient fingerprints),
  - invoked methods (used to follow the advertising / licensing call graph),
  - the opcode sequence (used for opcode-based fingerprints).

The parser is deliberately tolerant: a malformed ``code_item`` is skipped
instead of aborting the whole analysis, because obfuscated apps ship broken
debug information regularly.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

# Method access flags used by the analysis / fingerprint layer.
ACC_PUBLIC = 0x0001
ACC_PRIVATE = 0x0002
ACC_PROTECTED = 0x0004
ACC_STATIC = 0x0008
ACC_FINAL = 0x0010
ACC_SYNCHRONIZED = 0x0020
ACC_BRIDGE = 0x0040
ACC_VARARGS = 0x0080
ACC_NATIVE = 0x0100
ACC_ABSTRACT = 0x0400
ACC_SYNTHETIC = 0x1000
ACC_CONSTRUCTOR = 0x10000

# Dalvik opcodes we care about.
OP_CONST_STRING = 0x1A
OP_CONST_STRING_JUMBO = 0x1B
OP_RETURN_VOID = 0x0E

# Size in 16-bit code units of every opcode. Built from the DEX bytecode spec.
_INSN_SIZE = [1] * 256


def _set(opcodes: Sequence[int], size: int) -> None:
    for op in opcodes:
        _INSN_SIZE[op] = size


# --- moves / returns / constants -------------------------------------------------
_set(range(0x01, 0x0E), 1)
_set([0x02, 0x05, 0x08], 2)
_set([0x03, 0x06, 0x09], 3)
_set(range(0x0E, 0x12), 1)
_set([0x12], 1)
_set([0x13, 0x15, 0x16, 0x19, 0x1A, 0x1C], 2)
_set([0x14, 0x17, 0x1B], 3)
_set([0x18], 5)
_set([0x1D, 0x1E, 0x21, 0x27], 1)
_set([0x1F, 0x20, 0x22, 0x23], 2)
_set([0x24, 0x25, 0x26], 3)
_set([0x28], 1)
_set([0x29], 2)
_set([0x2A], 3)
_set([0x2B, 0x2C], 3)
_set(range(0x2D, 0x3E), 2)          # cmp* / if-*
_set(range(0x44, 0x6E), 2)          # aget/aput, iget/iput, sget/sput
_set(range(0x6E, 0x73), 3)          # invoke-*
_set(range(0x74, 0x79), 3)          # invoke-*/range
_set(range(0x7B, 0x90), 1)          # unary ops
_set(range(0x90, 0xB0), 2)          # binary ops
_set(range(0xB0, 0xD0), 1)          # binary op /2addr
_set(range(0xD0, 0xD8), 2)          # binary op /lit16
_set(range(0xD8, 0xE3), 2)          # binary op /lit8
_set([0xFA, 0xFB], 4)               # invoke-polymorphic
_set([0xFC, 0xFD], 3)               # invoke-custom
_set([0xFE, 0xFF], 2)               # const-method-handle / type

_INVOKE_OPS = set(range(0x6E, 0x73)) | set(range(0x74, 0x79))
# iget*/iput*/sget*/sput* (format 22c: field index in the second code unit).
_FIELD_OPS = set(range(0x52, 0x6E))


def _mutf8(data: bytes) -> str:
    """Decodes Modified UTF-8 as used by DEX string data."""
    try:
        return data.decode("utf-8", "replace")
    except Exception:  # pragma: no cover - defensive
        return data.decode("latin-1", "replace")


def read_uleb128(data: bytes, offset: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, offset
        shift += 7
        if shift > 35:
            raise ValueError("malformed uleb128")


def read_uleb128p1(data: bytes, offset: int) -> Tuple[int, int]:
    value, offset = read_uleb128(data, offset)
    return value - 1, offset


@dataclass
class MethodCode:
    """Decoded information about a single method body."""

    registers: int
    insns_count: int
    strings: List[str] = field(default_factory=list)
    called_methods: List[str] = field(default_factory=list)
    int_constants: List[int] = field(default_factory=list)
    # (opcode, register, value) for every const instruction, so a generated
    # patch can replace a blocking flag in place without guessing its register.
    literal_sites: List[tuple] = field(default_factory=list)
    # (opcode, "Lcom/foo/Bar;->field:Ljava/lang/String;", type) for every field
    # read/write. Preference delegates (``Lkotlin/Lazy;``) show up here.
    field_accesses: List[tuple] = field(default_factory=list)
    opcodes: List[int] = field(default_factory=list)
    complete: bool = True

    def opcode_names(self, limit: int = 24) -> List[str]:
        """Human-readable opcode sequence, collapses repeats for readability."""
        names: List[str] = []
        for op in self.opcodes[:limit]:
            names.append(OPCODE_NAMES.get(op, f"op_{op:02x}"))
        return names


@dataclass
class MethodInfo:
    """A method declared by a class of this DEX file."""

    dex: "DexFile"
    class_descriptor: str
    name: str
    descriptor: str           # e.g. (Ljava/lang/String;)Z
    return_type: str
    parameters: Tuple[str, ...]
    access_flags: int
    code_off: int
    _code: Optional[MethodCode] = None

    @property
    def full_name(self) -> str:
        return f"{self.class_descriptor}->{self.name}{self.descriptor}"

    @property
    def java_class(self) -> str:
        return descriptor_to_java(self.class_descriptor)

    @property
    def is_static(self) -> bool:
        return bool(self.access_flags & ACC_STATIC)

    @property
    def is_native(self) -> bool:
        return bool(self.access_flags & ACC_NATIVE)

    @property
    def is_abstract(self) -> bool:
        return bool(self.access_flags & ACC_ABSTRACT)

    @property
    def has_body(self) -> bool:
        return self.code_off > 0 and not self.is_native and not self.is_abstract

    def code(self) -> Optional[MethodCode]:
        if self._code is None and self.has_body:
            try:
                self._code = self.dex.decode_code(self.code_off)
            except Exception:
                self._code = MethodCode(0, 0, complete=False)
        return self._code

    def calls(self) -> List[str]:
        code = self.code()
        return list(code.called_methods) if code else []

    def uses_strings(self) -> List[str]:
        code = self.code()
        return list(code.strings) if code else []

    def reads_fields(self) -> List[str]:
        code = self.code()
        return [name for (_op, name, _type) in code.field_accesses] if code else []


@dataclass
class ClassInfo:
    descriptor: str
    super_descriptor: Optional[str]
    access_flags: int
    source_file: Optional[str]
    methods: List[MethodInfo] = field(default_factory=list)

    @property
    def java_name(self) -> str:
        return descriptor_to_java(self.descriptor)


def descriptor_to_java(descriptor: str) -> str:
    """``Lcom/foo/Bar;`` -> ``com.foo.Bar``, arrays/primitives kept readable."""
    if not descriptor:
        return descriptor
    if descriptor.startswith("L") and descriptor.endswith(";"):
        return descriptor[1:-1].replace("/", ".")
    dims = 0
    while dims < len(descriptor) and descriptor[dims] == "[":
        dims += 1
    base = descriptor[dims:]
    if base.startswith("L") and base.endswith(";"):
        base = base[1:-1].replace("/", ".")
    prefix = "[]" * dims
    return base + prefix


# A pragmatic subset of opcode names: enough for readable fingerprints and
# reports without shipping the full 256-entry table.
OPCODE_NAMES: Dict[int, str] = {
    0x00: "nop",
    0x01: "move", 0x02: "move/from16", 0x03: "move/16",
    0x04: "move-wide", 0x05: "move-wide/from16", 0x06: "move-wide/16",
    0x07: "move-object", 0x08: "move-object/from16", 0x09: "move-object/16",
    0x0A: "move-result", 0x0B: "move-result-wide", 0x0C: "move-result-object",
    0x0D: "move-exception",
    0x0E: "return-void", 0x0F: "return", 0x10: "return-wide", 0x11: "return-object",
    0x12: "const/4", 0x13: "const/16", 0x14: "const", 0x15: "const/high16",
    0x16: "const-wide/16", 0x17: "const-wide/32", 0x18: "const-wide",
    0x19: "const-wide/high16", 0x1A: "const-string", 0x1B: "const-string/jumbo",
    0x1C: "const-class",
    0x1D: "monitor-enter", 0x1E: "monitor-exit",
    0x1F: "check-cast", 0x20: "instance-of", 0x21: "array-length",
    0x22: "new-instance", 0x23: "new-array",
    0x24: "filled-new-array", 0x25: "filled-new-array/range",
    0x26: "fill-array-data", 0x27: "throw",
    0x28: "goto", 0x29: "goto/16", 0x2A: "goto/32",
    0x2B: "packed-switch", 0x2C: "sparse-switch",
    0x2D: "cmpl-float", 0x2E: "cmpg-float", 0x2F: "cmpl-double",
    0x30: "cmpg-double", 0x31: "cmp-long",
    0x32: "if-eq", 0x33: "if-ne", 0x34: "if-lt", 0x35: "if-ge",
    0x36: "if-gt", 0x37: "if-le",
    0x38: "if-eqz", 0x39: "if-nez", 0x3A: "if-ltz", 0x3B: "if-gez",
    0x3C: "if-gtz", 0x3D: "if-lez",
    0x44: "aget", 0x45: "aget-wide", 0x46: "aget-object", 0x47: "aget-boolean",
    0x4A: "aput", 0x4B: "aput-wide", 0x4C: "aput-object",
    0x52: "iget", 0x53: "iget-wide", 0x54: "iget-object", 0x55: "iget-boolean",
    0x59: "iput", 0x5A: "iput-wide", 0x5B: "iput-object", 0x5C: "iput-boolean",
    0x60: "sget", 0x61: "sget-wide", 0x62: "sget-object", 0x63: "sget-boolean",
    0x67: "sput", 0x68: "sput-wide", 0x69: "sput-object", 0x6A: "sput-boolean",
    0x6E: "invoke-virtual", 0x6F: "invoke-super", 0x70: "invoke-direct",
    0x71: "invoke-static", 0x72: "invoke-interface",
    0x74: "invoke-virtual/range", 0x75: "invoke-super/range",
    0x76: "invoke-direct/range", 0x77: "invoke-static/range",
    0x78: "invoke-interface/range",
}


class DexFile:
    """Random-access reader for one ``classes*.dex`` file."""

    def __init__(self, data: bytes, name: str = "classes.dex") -> None:
        if len(data) < 0x70 or not data.startswith(b"dex\n"):
            raise ValueError(f"{name} is not a DEX file")
        self.data = data
        self.name = name

        (string_ids_size, string_ids_off,
         type_ids_size, type_ids_off,
         proto_ids_size, proto_ids_off,
         field_ids_size, field_ids_off,
         method_ids_size, method_ids_off,
         class_defs_size, class_defs_off) = struct.unpack_from("<12I", data, 0x38)

        self.strings: List[str] = [
            self._read_string(off)
            for off in struct.unpack_from(f"<{string_ids_size}I", data, string_ids_off)
        ]

        self.types: List[str] = [
            self.strings[idx]
            for idx in struct.unpack_from(f"<{type_ids_size}I", data, type_ids_off)
        ]

        self.protos: List[Tuple[str, Tuple[str, ...]]] = []
        for i in range(proto_ids_size):
            shorty_idx, return_idx, params_off = struct.unpack_from(
                "<3I", data, proto_ids_off + i * 12
            )
            params: List[str] = []
            if params_off:
                size = struct.unpack_from("<I", data, params_off)[0]
                type_idxs = struct.unpack_from(f"<{size}H", data, params_off + 4)
                params = [self.types[t] for t in type_idxs]
            self.protos.append((self.types[return_idx], tuple(params)))

        self.method_refs: List[Tuple[str, str, str, Tuple[str, ...]]] = []
        for i in range(method_ids_size):
            class_idx, proto_idx, name_idx = struct.unpack_from(
                "<2HI", data, method_ids_off + i * 8
            )
            ret, params = self.protos[proto_idx]
            self.method_refs.append(
                (self.types[class_idx], self.strings[name_idx], ret, params)
            )

        self.field_refs: List[Tuple[str, str, str]] = []
        for i in range(field_ids_size):
            class_idx, type_idx, name_idx = struct.unpack_from(
                "<2HI", data, field_ids_off + i * 8
            )
            self.field_refs.append(
                (self.types[class_idx], self.strings[name_idx], self.types[type_idx])
            )

        self.classes: List[ClassInfo] = []
        for i in range(class_defs_size):
            (class_idx, access_flags, superclass_idx, _interfaces_off,
             source_file_idx, _annotations_off, class_data_off,
             _static_values_off) = struct.unpack_from("<8I", data, class_defs_off + i * 32)

            class_info = ClassInfo(
                descriptor=self.types[class_idx],
                super_descriptor=self.types[superclass_idx] if superclass_idx != 0xFFFFFFFF else None,
                access_flags=access_flags,
                source_file=(
                    self.strings[source_file_idx]
                    if source_file_idx != 0xFFFFFFFF and source_file_idx < len(self.strings)
                    else None
                ),
            )
            if class_data_off:
                try:
                    self._read_class_data(class_info, class_data_off)
                except Exception:
                    pass
            self.classes.append(class_info)

    # -- string helpers ---------------------------------------------------------
    def _read_string(self, offset: int) -> str:
        length, cursor = read_uleb128(self.data, offset)
        end = self.data.index(b"\x00", cursor)
        return _mutf8(self.data[cursor:end])

    # -- class data -------------------------------------------------------------
    def _read_class_data(self, info: ClassInfo, offset: int) -> None:
        data = self.data
        static_fields, offset = read_uleb128(data, offset)
        instance_fields, offset = read_uleb128(data, offset)
        direct_methods, offset = read_uleb128(data, offset)
        virtual_methods, offset = read_uleb128(data, offset)

        def skip_fields(count: int, cursor: int) -> int:
            for _ in range(count):
                _, cursor = read_uleb128(data, cursor)      # field_idx_diff
                _, cursor = read_uleb128(data, cursor)      # access_flags
            return cursor

        offset = skip_fields(static_fields, offset)
        offset = skip_fields(instance_fields, offset)

        for count in (direct_methods, virtual_methods):
            method_idx = 0
            for _ in range(count):
                diff, offset = read_uleb128(data, offset)
                method_idx += diff
                access_flags, offset = read_uleb128(data, offset)
                code_off, offset = read_uleb128(data, offset)
                if method_idx >= len(self.method_refs):
                    continue
                class_desc, name, ret, params = self.method_refs[method_idx]
                info.methods.append(MethodInfo(
                    dex=self,
                    class_descriptor=class_desc,
                    name=name,
                    descriptor="(" + "".join(params) + ")" + ret,
                    return_type=ret,
                    parameters=params,
                    access_flags=access_flags,
                    code_off=code_off,
                ))

    # -- bytecode ---------------------------------------------------------------
    def decode_code(self, code_off: int, max_insns: int = 20000) -> MethodCode:
        data = self.data
        (registers, ins, _outs, tries_size, _debug_off, insns_size) = struct.unpack_from(
            "<4H2I", data, code_off
        )
        insns_off = code_off + 16
        end = min(insns_size, max_insns)
        result = MethodCode(registers=registers, insns_count=insns_size)

        strings: List[str] = []
        called: List[str] = []
        constants: List[int] = []
        sites: List[tuple] = []
        fields: List[tuple] = []
        opcodes: List[int] = []

        unit = 0
        while unit < end:
            offset = insns_off + unit * 2
            word = struct.unpack_from("<H", data, offset)[0]
            op = word & 0xFF

            if op == 0x00:  # nop or payload pseudo-instruction
                ident = word
                if ident == 0x0100:      # packed-switch payload
                    size = struct.unpack_from("<H", data, offset + 2)[0]
                    unit += size * 2 + 4
                    continue
                if ident == 0x0200:      # sparse-switch payload
                    size = struct.unpack_from("<H", data, offset + 2)[0]
                    unit += size * 4 + 2
                    continue
                if ident == 0x0300:      # fill-array-data payload
                    elem_width, size = struct.unpack_from("<HI", data, offset + 2)
                    unit += (elem_width * size + 1) // 2 + 4
                    continue
                opcodes.append(op)
                unit += 1
                continue

            if op in (OP_CONST_STRING, OP_CONST_STRING_JUMBO):
                if op == OP_CONST_STRING:
                    idx = struct.unpack_from("<H", data, offset + 2)[0]
                else:
                    idx = struct.unpack_from("<I", data, offset + 2)[0]
                if idx < len(self.strings):
                    strings.append(self.strings[idx])
            elif op in _INVOKE_OPS:
                idx = struct.unpack_from("<H", data, offset + 2)[0]
                if idx < len(self.method_refs):
                    class_desc, name, ret, params = self.method_refs[idx]
                    called.append(f"{class_desc}->{name}({''.join(params)}){ret}")
            elif op in _FIELD_OPS:
                idx = struct.unpack_from("<H", data, offset + 2)[0]
                if idx < len(self.field_refs):
                    class_desc, name, field_type = self.field_refs[idx]
                    fields.append((op, f"{class_desc}->{name}:{field_type}", field_type))
            elif op == 0x12:  # const/4
                value = word >> 12
                if value & 0x8:
                    value -= 0x10
                constants.append(value)
                sites.append((op, (word >> 8) & 0xF, value))
            elif op == 0x13:  # const/16
                value = struct.unpack_from("<h", data, offset + 2)[0]
                constants.append(value)
                sites.append((op, (word >> 8) & 0xFF, value))
            elif op == 0x15:  # const/high16
                value = struct.unpack_from("<h", data, offset + 2)[0] << 16
                constants.append(value)
                sites.append((op, (word >> 8) & 0xFF, value))
            elif op == 0x14:  # const (32 bit)
                value = struct.unpack_from("<i", data, offset + 2)[0]
                constants.append(value)
                sites.append((op, (word >> 8) & 0xFF, value))
            elif op == 0x16:  # const-wide/16
                constants.append(struct.unpack_from("<h", data, offset + 2)[0])
            elif op == 0x17:  # const-wide/32
                constants.append(struct.unpack_from("<i", data, offset + 2)[0])

            opcodes.append(op)
            unit += _INSN_SIZE[op]

        result.strings = strings
        result.called_methods = called
        result.int_constants = constants
        result.literal_sites = sites
        result.field_accesses = fields
        result.opcodes = opcodes
        result.complete = unit <= end + 8
        return result

    # -- iteration --------------------------------------------------------------
    def iter_methods(self) -> Iterator[MethodInfo]:
        for cls in self.classes:
            yield from cls.methods


def looks_like_obfuscated(name: str) -> bool:
    """Heuristic: single/double letter class or method names (R8/ProGuard)."""
    if len(name) <= 2:
        return True
    return False
