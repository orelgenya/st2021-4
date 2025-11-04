#!/usr/bin/env python3
"""Build an AsyncAPI document that showcases the BXF use-case examples."""
from __future__ import annotations

import argparse
import copy
import json
import uuid
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
                if fragment:
                    fragment_text = fragment if fragment.startswith("/") else f"/{fragment}"
                else:
                    fragment_text = ""
                return f"#/components/schemas/{mapped}{fragment_text}"
        return node

    normalised: Dict[str, Dict[str, Any]] = {}
    for name, schema in catalog.items():
        normalised[name] = rewrite_refs(copy.deepcopy(schema))
    return normalised


def build_examples(paths: List[Path]) -> List[Dict[str, Any]]:
    examples: List[Dict[str, Any]] = []
    for path in paths:
        examples.append(
            {
                "name": path.stem,
                "summary": path.stem,
                "payload": load_xml(path),
            }
        )
    return examples


def build_document(usecase_dir: Path, schema_dir: Path, *, inline_payload: bool) -> str:
    mapping = parse_usecases(usecase_dir)
    schema_ref = schema_dir.joinpath("bxfschema.schema.json")
    payload_ref = f"{schema_ref.as_posix()}#/$defs/BxfMessage"

    document: Dict[str, Any] = {
        "asyncapi": ASYNCAPI_VERSION,
        "id": "urn:uuid:" + str(uuid.UUID("12345678-1234-5678-1234-567812345678")),
        "info": {
            "title": "BXF Use Case Library",
            "version": "1.0.0",
            "description": (
                "AsyncAPI catalogue derived from the SMPTE ST 2021-4 sample messages. "
                "Each channel groups documented use cases that share the same BXF "
                "messageType attribute."
            ),
            "contact": {
                "name": "SMPTE BXF Working Group",
                "url": "https://www.smpte.org/standards",
            },
            "license": {
                "name": "SMPTE ST 2021-4 License",
                "url": "https://github.com/SMPTE/st2021-4/blob/main/LICENSE.md",
            },
        },
        "defaultContentType": "application/xml",
        "servers": {
            "sandbox": {
                "host": "bxf.example.test",
                "protocol": "ws",
                "description": "Illustrative server endpoint for sample message flows.",
            }
        },
        "tags": [
            {"name": "bxf"},
            {"name": "asyncapi"},
        ],
        "channels": {},
        "components": {"messages": {}},
    }

    if inline_payload:
        schemas = load_schema_catalog(schema_dir)
        document["components"]["schemas"] = schemas
        payload_pointer = "#/components/schemas/bxfschema/$defs/BxfMessage"
    else:
        payload_pointer = payload_ref

    for message_type, paths in mapping.items():
        channel_name = message_type.replace(" ", "_")
        message_key = message_type.replace(" ", "")
        message_name = f"Bxf{message_key}Message"

        document["channels"][channel_name] = {
            "description": "BXF channel grouped by messageType",
            "subscribe": {
                "summary": "Receive BXF messages of this type",
                "operationId": f"receive{message_key}",
                "message": {"$ref": f"#/components/messages/{message_name}"},
            },
        }

        message: Dict[str, Any] = {
            "name": message_type,
            "summary": f"BXF {message_type} message",
            "messageId": f"urn:message:bxf:{message_key}",
            "examples": build_examples(paths),
        }

        if inline_payload:
            message["payload"] = {"$ref": payload_pointer}
        else:
            message["schemaFormat"] = "application/schema+json;version=draft-2020-12"
            message["payload"] = {"$ref": payload_pointer}

        document["components"]["messages"][message_name] = message

    return json.dumps(document, indent=2) + "\n"


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
