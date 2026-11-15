"""
Minimal Android binary XML (AXML) decoder.

``AndroidManifest.xml`` inside an APK is compiled to the binary XML format
(``resources.arsc`` string pool + typed attribute values). Decoding it lets
Morphy read the package name, version, SDK levels and permissions without
requiring Apktool or the Android SDK.

Only the chunk types needed for manifest/report display are handled.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional

RES_STRING_POOL_TYPE = 0x0001
RES_XML_TYPE = 0x0003
RES_XML_RESOURCE_MAP_TYPE = 0x0180
RES_XML_START_NAMESPACE_TYPE = 0x0100
RES_XML_END_NAMESPACE_TYPE = 0x0101
RES_XML_START_ELEMENT_TYPE = 0x0102
RES_XML_END_ELEMENT_TYPE = 0x0103
RES_XML_CDATA_TYPE = 0x0104

TYPE_REFERENCE = 0x01
TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11
TYPE_INT_BOOLEAN = 0x12


class AxmlError(Exception):
    pass


@dataclass
class XmlElement:
    tag: str
    attributes: Dict[str, str] = field(default_factory=dict)
    resource_ids: Dict[str, int] = field(default_factory=dict)
    children: List["XmlElement"] = field(default_factory=list)
    parent: Optional["XmlElement"] = None

    def find_all(self, tag: str) -> List["XmlElement"]:
        found: List["XmlElement"] = []
        stack = list(self.children)
        while stack:
            node = stack.pop()
            if node.tag == tag:
                found.append(node)
            stack.extend(node.children)
        return found

    def get(self, name: str, default: str = "") -> str:
        return self.attributes.get(name, default)


def _read_string_pool(data: bytes, offset: int) -> List[str]:
    (chunk_type, header_size, chunk_size,
     string_count, _style_count, flags,
     strings_start, _styles_start) = struct.unpack_from("<2H2I2I2I", data, offset)

    if chunk_type != RES_STRING_POOL_TYPE:
        raise AxmlError("expected a string pool chunk")

    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{string_count}I", data, offset + header_size)
    base = offset + strings_start
    strings: List[str] = []

    for rel in offsets:
        cursor = base + rel
        if utf8:
            # UTF-16 length (skipped), then UTF-8 length, then the bytes.
            _, cursor = _len8(data, cursor)
            length, cursor = _len8(data, cursor)
            raw = data[cursor:cursor + length]
            strings.append(raw.decode("utf-8", "replace"))
        else:
            length = struct.unpack_from("<H", data, cursor)[0]
            cursor += 2
            if length & 0x8000:
                low = struct.unpack_from("<H", data, cursor)[0]
                cursor += 2
                length = ((length & 0x7FFF) << 16) | low
            raw = data[cursor:cursor + length * 2]
            strings.append(raw.decode("utf-16-le", "replace"))

    return strings


def _len8(data: bytes, offset: int):
    value = data[offset]
    offset += 1
    if value & 0x80:
        value = ((value & 0x7F) << 8) | data[offset]
        offset += 1
    return value, offset


def parse_axml(data: bytes) -> XmlElement:
    """Parses binary XML and returns a synthetic root element."""
    if len(data) < 8:
        raise AxmlError("file is too small to be binary XML")

    chunk_type, header_size, total_size = struct.unpack_from("<2HI", data, 0)
    if chunk_type != RES_XML_TYPE:
        raise AxmlError("not an Android binary XML document")

    strings: List[str] = []
    resource_ids: List[int] = []
    root = XmlElement("#document")
    stack: List[XmlElement] = [root]

    offset = header_size
    end = min(total_size, len(data))

    while offset + 8 <= end:
        ctype, cheader, csize = struct.unpack_from("<2HI", data, offset)
        if csize <= 0:
            break

        if ctype == RES_STRING_POOL_TYPE:
            strings = _read_string_pool(data, offset)
        elif ctype == RES_XML_RESOURCE_MAP_TYPE:
            count = (csize - cheader) // 4
            resource_ids = list(struct.unpack_from(f"<{count}I", data, offset + cheader))
        elif ctype == RES_XML_START_ELEMENT_TYPE:
            node = _read_start_element(data, offset, strings, resource_ids)
            node.parent = stack[-1]
            stack[-1].children.append(node)
            stack.append(node)
        elif ctype == RES_XML_END_ELEMENT_TYPE:
            if len(stack) > 1:
                stack.pop()

        offset += csize

    return root


def _read_start_element(
    data: bytes, offset: int, strings: List[str], resource_ids: List[int]
) -> XmlElement:
    # Chunk header: type/headerSize/size (8 bytes)
    # Then lineNumber/comment (8 bytes) -> the "attrExt" structure starts at +16.
    #   ns(4) name(4) attributeStart(2) attributeSize(2)
    #   attributeCount(2) idIndex(2) classIndex(2) styleIndex(2)
    attr_ext = offset + 16
    ns_idx, name_idx, attr_start, attr_size, attr_count, *_ = struct.unpack_from(
        "<2I4H", data, attr_ext
    )
    tag = strings[name_idx] if name_idx < len(strings) else f"<{name_idx}>"
    element = XmlElement(tag)

    cursor = attr_ext + (attr_start or 20)
    for _ in range(attr_count):
        if cursor + 20 > len(data):
            break
        attr_ns, attr_name, attr_raw = struct.unpack_from("<3I", data, cursor)
        value_size, _res0, value_type, value_data = struct.unpack_from(
            "<HBBI", data, cursor + 12
        )

        name = strings[attr_name] if attr_name < len(strings) else f"attr{attr_name}"
        is_android = attr_ns < len(strings) and strings[attr_ns].endswith(
            "android.com/apk/res/android"
        ) if attr_ns < len(strings) else False

        if attr_raw < len(strings):
            value = strings[attr_raw]
        elif value_type == TYPE_STRING and value_data < len(strings):
            value = strings[value_data]
        elif value_type == TYPE_INT_BOOLEAN:
            value = "true" if value_data else "false"
        elif value_type == TYPE_INT_DEC:
            value = str(_signed32(value_data))
        elif value_type == TYPE_INT_HEX:
            value = f"0x{value_data:x}"
        elif value_type == TYPE_REFERENCE:
            value = f"@{value_data:#010x}"
        else:
            value = str(value_data)

        key = f"android:{name}" if is_android else name
        element.attributes[key] = value
        if attr_name < len(resource_ids):
            element.resource_ids[key] = resource_ids[attr_name]

        cursor += attr_size or 20

    return element


def _signed32(value: int) -> int:
    return value - 0x100000000 if value & 0x80000000 else value
