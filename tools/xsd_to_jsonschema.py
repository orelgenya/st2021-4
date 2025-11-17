#!/usr/bin/env python3
"""Convert SMPTE BXF XSD files into JSON Schema Draft 2020-12."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import xml.etree.ElementTree as ET

XSD_NS = "{http://www.w3.org/2001/XMLSchema}"


def qname(local: str) -> str:
    return f"{XSD_NS}{local}"


class XsdConverter:
    """Very small XML Schema -> JSON Schema converter for the BXF schemas.

    The BXF schemas mainly use sequences, choices, simple restrictions and
    attributes.  The converter implements the minimum logic required to produce
    JSON Schema documentation that mirrors the XML structure closely enough for
    documentation / validation purposes.
    """

    def __init__(self, search_paths: Iterable[Path]):
        self.search_paths = list(search_paths)
        self.type_nodes: Dict[Tuple[str, str], ET.Element] = {}
        self.element_nodes: Dict[Tuple[str, str], ET.Element] = {}
        self.type_locations: Dict[Tuple[str, str], Path] = {}
        self.element_locations: Dict[Tuple[str, str], Path] = {}
        self.target_namespaces: Dict[Path, str] = {}
        for path in self.search_paths:
            self._index_schema(path)

    def _index_schema(self, path: Path) -> None:
        tree = ET.parse(path)
        root = tree.getroot()
        tns = root.attrib.get("targetNamespace", "")
        self.target_namespaces[path] = tns
        for child in root:
            if child.tag in {qname("complexType"), qname("simpleType")}:
                name = child.attrib.get("name")
                if name:
                    key = (tns, name)
                    self.type_nodes[key] = child
                    self.type_locations[key] = path
            elif child.tag == qname("element"):
                name = child.attrib.get("name")
                if name:
                    key = (tns, name)
                    self.element_nodes[key] = child
                    self.element_locations[key] = path

    def convert(self, path: Path) -> Dict[str, object]:
        tree = ET.parse(path)
        root = tree.getroot()
        tns = root.attrib.get("targetNamespace", "")
        schema: Dict[str, object] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": self._build_schema_id(path, tns),
            "title": path.stem,
            "type": "object",
            "properties": {},
            "$defs": {},
            "additionalProperties": False,
        }
        defs: Dict[str, object] = schema["$defs"]  # type: ignore[assignment]

        for child in root:
            if child.tag == qname("element"):
                name = child.attrib.get("name")
                if not name:
                    continue
                defs[name] = self._convert_element(child, tns, path)
            elif child.tag in {qname("complexType"), qname("simpleType")}:
                name = child.attrib.get("name")
                if not name:
                    continue
                defs[name] = self._convert_type(child, tns, path)

        return schema

    def _build_schema_id(self, path: Path, namespace: str) -> str:
        if namespace:
            return namespace.rstrip("/") + f"/{path.stem}.schema.json"
        return path.stem

    def _convert_element(self, elem: ET.Element, tns: str, source: Path) -> Dict[str, object]:
        result: Dict[str, object] = {
            "title": elem.attrib.get("name", "element"),
        }
        type_name = elem.attrib.get("type")
        if type_name:
            result.update(self._ref_for_type(type_name, tns, source))
        else:
            for child in elem:
                if child.tag in {qname("complexType"), qname("simpleType")}:
                    result.update(self._convert_type(child, tns, source))
        min_occurs = int(elem.attrib.get("minOccurs", "1"))
        max_occurs = elem.attrib.get("maxOccurs", "1")
        if max_occurs == "unbounded" or int(max_occurs) > 1:
            items = {k: v for k, v in result.items() if k not in {"title"}}
            result.clear()
            result["type"] = "array"
            result["items"] = items
            if min_occurs:
                result["minItems"] = min_occurs
            if max_occurs != "unbounded":
                result["maxItems"] = int(max_occurs)
        else:
            if "$ref" not in result:
                result.setdefault("type", "object")
        annotation = elem.find(qname("annotation"))
        if annotation is not None:
            doc = annotation.find(qname("documentation"))
            if doc is not None and doc.text:
                result["description"] = doc.text.strip()
        return result

    def _convert_type(self, elem: ET.Element, tns: str, source: Path) -> Dict[str, object]:
        if elem.tag == qname("simpleType"):
            return self._convert_simple_type(elem, tns, source)
        return self._convert_complex_type(elem, tns, source)

    def _convert_simple_type(self, elem: ET.Element, tns: str, source: Path) -> Dict[str, object]:
        restriction = elem.find(qname("restriction"))
        if restriction is not None:
            return self._convert_restriction(restriction, tns, source)
        union = elem.find(qname("union"))
        if union is not None:
            return self._convert_union(union, tns, source)
        lst = elem.find(qname("list"))
        if lst is not None:
            return self._convert_list(lst, tns, source)
        return {"type": "string"}

    def _convert_complex_type(self, elem: ET.Element, tns: str, source: Path) -> Dict[str, object]:
        result: Dict[str, object] = {"type": "object", "properties": {}, "additionalProperties": False}
        required: List[str] = []
        for child in elem:
            if child.tag == qname("annotation"):
                doc = child.find(qname("documentation"))
                if doc is not None and doc.text:
                    result["description"] = doc.text.strip()
            elif child.tag == qname("sequence"):
                self._handle_sequence(child, result, required, tns, source)
            elif child.tag == qname("choice"):
                self._handle_choice(child, result, tns, source)
            elif child.tag == qname("all"):
                self._handle_sequence(child, result, required, tns, source)
            elif child.tag == qname("attribute"):
                self._handle_attribute(child, result, required, tns, source)
            elif child.tag == qname("simpleContent"):
                self._handle_simple_content(child, result, tns, source)
            elif child.tag == qname("complexContent"):
                self._handle_complex_content(child, result, tns, source)
        if required:
            result["required"] = required
        if not result.get("properties"):
            result.pop("properties", None)
            result.pop("additionalProperties", None)
        return result

    def _handle_sequence(
        self,
        node: ET.Element,
        result: Dict[str, object],
        required: List[str],
        tns: str,
        source: Path,
    ) -> None:
        props = result.setdefault("properties", {})  # type: ignore[assignment]
        for child in node:
            if child.tag == qname("element"):
                name = child.attrib.get("name")
                if not name:
                    continue
                child_schema = self._convert_element(child, tns, source)
                props[name] = child_schema
                min_occurs = int(child.attrib.get("minOccurs", "1"))
                if min_occurs > 0:
                    required.append(name)
            elif child.tag == qname("choice"):
                self._handle_choice(child, result, tns, source)
            elif child.tag == qname("any"):
                result["additionalProperties"] = True

    def _handle_choice(self, node: ET.Element, result: Dict[str, object], tns: str, source: Path) -> None:
        options: List[Dict[str, object]] = []
        for child in node:
            if child.tag == qname("element"):
                name = child.attrib.get("name")
                if not name:
                    continue
                option_schema = {
                    "type": "object",
                    "properties": {name: self._convert_element(child, tns, source)},
                    "additionalProperties": False,
                }
                min_occurs = int(child.attrib.get("minOccurs", "1"))
                if min_occurs:
                    option_schema["required"] = [name]
                options.append(option_schema)
        if options:
            result.setdefault("oneOf", [])  # type: ignore[assignment]
            result["oneOf"].extend(options)  # type: ignore[index]

    def _handle_attribute(
        self, node: ET.Element, result: Dict[str, object], required: List[str], tns: str, source: Path
    ) -> None:
        name = node.attrib.get("name")
        if not name:
            return
        props = result.setdefault("properties", {})  # type: ignore[assignment]
        attr_schema: Dict[str, object] = {}
        type_name = node.attrib.get("type")
        if type_name:
            attr_schema.update(self._ref_for_type(type_name, tns, source))
        else:
            for child in node:
                if child.tag in {qname("simpleType"), qname("complexType")}:
                    attr_schema.update(self._convert_type(child, tns, source))
        props[f"@{name}"] = attr_schema
        if node.attrib.get("use") == "required":
            required.append(f"@{name}")

    def _handle_simple_content(self, node: ET.Element, result: Dict[str, object], tns: str, source: Path) -> None:
        extension = node.find(qname("extension"))
        restriction = node.find(qname("restriction"))
        if extension is not None:
            base = extension.attrib.get("base")
            if base:
                result.update(self._ref_for_type(base, tns, source))
            for child in extension:
                if child.tag == qname("attribute"):
                    req = result.setdefault("required", [])  # type: ignore[assignment]
                    self._handle_attribute(child, result, req, tns, source)  # type: ignore[arg-type]
        elif restriction is not None:
            result.update(self._convert_restriction(restriction, tns, source))

    def _handle_complex_content(self, node: ET.Element, result: Dict[str, object], tns: str, source: Path) -> None:
        extension = node.find(qname("extension"))
        if extension is not None:
            base = extension.attrib.get("base")
            if base:
                base_schema = self._ref_for_type(base, tns, source)
                if "$ref" in base_schema:
                    result.setdefault("allOf", []).append(base_schema)
                else:
                    for key, value in base_schema.items():
                        result.setdefault(key, value)
            for child in extension:
                if child.tag == qname("sequence"):
                    req = result.setdefault("required", [])  # type: ignore[assignment]
                    self._handle_sequence(child, result, req, tns, source)  # type: ignore[arg-type]
                elif child.tag == qname("attribute"):
                    req = result.setdefault("required", [])  # type: ignore[assignment]
                    self._handle_attribute(child, result, req, tns, source)  # type: ignore[arg-type]

    def _convert_restriction(self, node: ET.Element, tns: str, source: Path) -> Dict[str, object]:
        base = node.attrib.get("base")
        schema = self._ref_for_type(base, tns, source) if base else {}
        for child in node:
            if child.tag == qname("enumeration"):
                schema.setdefault("enum", []).append(child.attrib["value"])  # type: ignore[index]
            elif child.tag == qname("pattern"):
                schema["pattern"] = child.attrib["value"]
            elif child.tag == qname("minLength"):
                schema["minLength"] = int(child.attrib["value"])
            elif child.tag == qname("maxLength"):
                schema["maxLength"] = int(child.attrib["value"])
            elif child.tag == qname("minInclusive"):
                schema["minimum"] = self._parse_numeric(child.attrib["value"])
            elif child.tag == qname("maxInclusive"):
                schema["maximum"] = self._parse_numeric(child.attrib["value"])
            elif child.tag == qname("minExclusive"):
                schema["exclusiveMinimum"] = self._parse_numeric(child.attrib["value"])
            elif child.tag == qname("maxExclusive"):
                schema["exclusiveMaximum"] = self._parse_numeric(child.attrib["value"])
        return schema

    def _convert_union(self, node: ET.Element, tns: str, source: Path) -> Dict[str, object]:
        members = node.attrib.get("memberTypes", "").split()
        schemas = [self._ref_for_type(member, tns, source) for member in members if member]
        for child in node:
            if child.tag == qname("simpleType"):
                schemas.append(self._convert_simple_type(child, tns, source))
        if len(schemas) == 1:
            return schemas[0]
        return {"anyOf": schemas}

    def _convert_list(self, node: ET.Element, tns: str, source: Path) -> Dict[str, object]:
        item_type = node.attrib.get("itemType")
        if item_type:
            items = self._ref_for_type(item_type, tns, source)
        else:
            child = node.find(qname("simpleType"))
            items = self._convert_simple_type(child, tns, source) if child is not None else {"type": "string"}
        return {"type": "array", "items": items}

    def _ref_for_type(self, type_name: Optional[str], tns: str, source: Path) -> Dict[str, object]:
        if not type_name:
            return {"type": "string"}
        if type_name.startswith("xs:"):
            return builtin_type(type_name[3:])
        if ":" in type_name:
            prefix, local = type_name.split(":", 1)
            if prefix in {"xml", "pmcp"}:
                return {"type": "string"}
            namespace = tns
            if prefix == "tns":
                namespace = tns
            # fallback to default namespace
            key = (namespace, local)
        else:
            key = (tns, type_name)
        if key in self.type_nodes:
            target = self.type_locations.get(key)
            if target == source:
                return {"$ref": f"#/$defs/{key[1]}"}
            if target is not None:
                rel = target.with_suffix(".schema.json").name
                return {"$ref": f"./{rel}#/$defs/{key[1]}"}
        if key in self.element_nodes:
            target = self.element_locations.get(key)
            if target == source:
                return {"$ref": f"#/$defs/{key[1]}"}
            if target is not None:
                rel = target.with_suffix(".schema.json").name
                return {"$ref": f"./{rel}#/$defs/{key[1]}"}
        return {"type": "string"}

    @staticmethod
    def _parse_numeric(value: str):
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value


def builtin_type(name: str) -> Dict[str, object]:
    mapping = {
        "string": {"type": "string"},
        "normalizedString": {"type": "string"},
        "token": {"type": "string"},
        "language": {"type": "string"},
        "Name": {"type": "string"},
        "NCName": {"type": "string"},
        "NMTOKEN": {"type": "string"},
        "anyURI": {"type": "string", "format": "uri"},
        "date": {"type": "string", "format": "date"},
        "dateTime": {"type": "string", "format": "date-time"},
        "time": {"type": "string", "format": "time"},
        "duration": {"type": "string"},
        "boolean": {"type": "boolean"},
        "decimal": {"type": "number"},
        "float": {"type": "number"},
        "double": {"type": "number"},
        "integer": {"type": "integer"},
        "nonNegativeInteger": {"type": "integer", "minimum": 0},
        "positiveInteger": {"type": "integer", "minimum": 1},
        "nonPositiveInteger": {"type": "integer", "maximum": 0},
        "negativeInteger": {"type": "integer", "maximum": -1},
        "long": {"type": "integer"},
        "int": {"type": "integer"},
        "short": {"type": "integer"},
        "byte": {"type": "integer"},
        "unsignedLong": {"type": "integer", "minimum": 0},
        "unsignedInt": {"type": "integer", "minimum": 0},
        "unsignedShort": {"type": "integer", "minimum": 0},
        "unsignedByte": {"type": "integer", "minimum": 0},
        "base64Binary": {"type": "string", "contentEncoding": "base64"},
    }
    return mapping.get(name, {"type": "string"})


def main(argv: List[str]) -> int:
    if len(argv) < 3:
        print("Usage: xsd_to_jsonschema.py <xsd_directory> <output_directory>")
        return 1
    xsd_dir = Path(argv[1])
    out_dir = Path(argv[2])
    paths = sorted(p for p in xsd_dir.glob("*.xsd") if p.is_file())
    converter = XsdConverter(paths)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        schema = converter.convert(path)
        output_path = out_dir / f"{path.stem}.schema.json"
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(schema, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
