#!/usr/bin/env python3
"""Build an AsyncAPI document that showcases the BXF use-case examples."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Dict, List
import xml.etree.ElementTree as ET

ASYNCAPI_VERSION = "3.0.0"


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


def build_document(usecase_dir: Path, schema_dir: Path) -> str:
    mapping = parse_usecases(usecase_dir)
    lines = [
        "asyncapi: 3.0.0",
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
    schema_ref = schema_dir.joinpath("bxfschema.schema.json")
    payload_ref = f"{schema_ref.as_posix()}#/$defs/BxfMessage"

    for message_type, paths in mapping.items():
        channel_name = message_type.replace(" ", "_")
        message_key = message_type.replace(" ", "")
        message_name = f"Bxf{message_key}Message"
        lines.extend(
            [
                f"  {channel_name}:",
                f"    address: bxf/{message_type}",
                "    messages:",
                f"      {message_name}:",
                f"        $ref: '#/components/messages/{message_name}'",
                "    subscribe:",
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
                "      schemaFormat: application/schema+json;version=draft-2020-12",
                "      payload:",
                f"        $ref: '{payload_ref}'",
                "      examples:",
            ]
        )
        components.extend(example_lines or ["      []"])

    return "\n".join(lines + components) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("usecases", type=Path)
    parser.add_argument("schema_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    document = build_document(args.usecases, args.schema_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
