#!/usr/bin/env python3
"""Build an AsyncAPI document that showcases the BXF use-case examples."""
from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List
import xml.etree.ElementTree as ET

ASYNCAPI_VERSION = "2.6.0"


def parse_usecases(directory: Path) -> Dict[str, List[Path]]:
    mapping: Dict[str, List[Path]] = defaultdict(list)
    for path in sorted(directory.glob("*.xml")):
        tree = ET.parse(path)
        root = tree.getroot()
        message_type = root.attrib.get("messageType") or path.stem
        mapping[message_type].append(path)
    return mapping


def load_xml(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith("<?xml"):
        return text
    # Keep declaration but indent body for nicer rendering.
    lines = text.splitlines()
    header, body = lines[0], lines[1:]
    indented = "\n".join(body)
    return "\n".join([header, indented])


def load_schema_catalog(schema_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Load and normalize the generated JSON Schemas for inline embedding."""

    def schema_name(path: Path) -> str:
        name = path.name
        if name.endswith(".schema.json"):
            name = name[: -len(".schema.json")]
        return name

    catalog: Dict[str, Dict[str, Any]] = {}
    for path in sorted(schema_dir.glob("*.schema.json")):
        catalog[schema_name(path)] = json.loads(path.read_text(encoding="utf-8"))

    lookup = {f"{name}.schema.json": name for name in catalog}

    def rewrite_refs(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: rewrite_refs(value) for key, value in node.items()}
        if isinstance(node, list):
            return [rewrite_refs(item) for item in node]
        if isinstance(node, str) and node.startswith("./") and ".schema.json" in node:
            path_and_fragment = node[2:]
            filename, _, fragment = path_and_fragment.partition("#")
            mapped = lookup.get(filename)
            if mapped is not None:
                fragment_text = f"#{fragment}" if fragment else ""
                return f"#/components/schemas/{mapped}{fragment_text}"
        return node

    normalised: Dict[str, Dict[str, Any]] = {}
    for name, schema in catalog.items():
        normalised[name] = rewrite_refs(copy.deepcopy(schema))
    return normalised


def dump_yaml(node: Any, indent: int) -> List[str]:
    """Serialise basic Python structures to YAML-compatible lines."""

    def format_scalar(value: Any) -> str:
        return json.dumps(value)

    if isinstance(node, dict):
        lines: List[str] = []
        if not node:
            lines.append(" " * indent + "{}")
            return lines
        for key, value in node.items():
            if isinstance(value, dict):
                if value:
                    lines.append(" " * indent + f"{key}:")
                    lines.extend(dump_yaml(value, indent + 2))
                else:
                    lines.append(" " * indent + f"{key}: {{}}")
            elif isinstance(value, list):
                if value:
                    lines.append(" " * indent + f"{key}:")
                    lines.extend(dump_yaml(value, indent + 2))
                else:
                    lines.append(" " * indent + f"{key}: []")
            else:
                lines.append(" " * indent + f"{key}: {format_scalar(value)}")
        return lines
    if isinstance(node, list):
        lines = []
        if not node:
            lines.append(" " * indent + "[]")
            return lines
        for item in node:
            if isinstance(item, (dict, list)):
                lines.append(" " * indent + "-")
                lines.extend(dump_yaml(item, indent + 2))
            else:
                lines.append(" " * indent + f"- {format_scalar(item)}")
        return lines
    return [" " * indent + format_scalar(node)]


def build_document(usecase_dir: Path, schema_dir: Path, *, inline_payload: bool) -> str:
    mapping = parse_usecases(usecase_dir)
    lines = [
        f"asyncapi: {ASYNCAPI_VERSION}",
        "info:",
        "  title: BXF Use Case Library",
        "  version: 1.0.0",
        "  description: |",
        "    AsyncAPI catalogue derived from the SMPTE ST 2021-4 sample messages.",
        "    Each channel groups documented use cases that share the same BXF",
        "    messageType attribute.",
        "defaultContentType: application/xml",
        "servers:",
        "  sandbox:",
        "    host: bxf.example.test",
        "    protocol: ws",
        "channels:",
    ]
    components: List[str] = ["components:", "  messages:"]
    schemas: Dict[str, Dict[str, Any]] = {}
    schema_ref = schema_dir.joinpath("bxfschema.schema.json")
    payload_ref = f"{schema_ref.as_posix()}#/$defs/BxfMessage"

    for message_type, paths in mapping.items():
        channel_name = message_type.replace(" ", "_")
        message_key = message_type.replace(" ", "")
        message_name = f"Bxf{message_key}Message"
        lines.extend(
            [
                f"  {channel_name}:",
                "    description: BXF channel grouped by messageType",
                "    subscribe:",
                "      summary: Receive BXF messages of this type",
                "      message:",
                f"        $ref: '#/components/messages/{message_name}'",
            ]
        )
        example_lines: List[str] = []
        for path in paths:
            example_lines.append("      - name: " + path.stem)
            example_lines.append("        summary: " + path.stem)
            example_lines.append("        payload: |")
            xml_text = load_xml(path)
            for xml_line in xml_text.splitlines():
                example_lines.append("          " + xml_line)
        components.extend(
            [
                f"    {message_name}:",
                f"      name: {message_type}",
                f"      summary: BXF {message_type} message",
            ]
        )
        if inline_payload:
            schemas = schemas or load_schema_catalog(schema_dir)
            components.extend(
                [
                    "      payload:",
                    f"        $ref: '#/components/schemas/bxfschema#/$defs/BxfMessage'",
                ]
            )
        else:
            components.extend(
                [
                    "      schemaFormat: application/schema+json;version=draft-2020-12",
                    "      payload:",
                    f"        $ref: '{payload_ref}'",
                ]
            )
        components.append("      examples:")
        components.extend(example_lines or ["      []"])

    if inline_payload and schemas:
        components.append("  schemas:")
        for name, schema in schemas.items():
            components.append(f"    {name}:")
            components.extend(dump_yaml(schema, indent=6))

    return "\n".join(lines + components) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("usecases", type=Path)
    parser.add_argument("schema_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Embed a descriptive payload instead of referencing the JSON Schema file.",
    )
    args = parser.parse_args()
    document = build_document(args.usecases, args.schema_dir, inline_payload=args.inline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
