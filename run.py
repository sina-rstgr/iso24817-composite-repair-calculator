"""Command-line interface for the ISO 24817 Type A repair calculator."""
from __future__ import annotations


import argparse
import json
import sys
from contextlib import redirect_stdout
from dataclasses import fields
from io import StringIO
from pathlib import Path

from calculator import RepairInputs, calculate_repair, print_report


def load_inputs(path: Path) -> RepairInputs:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    allowed = {field.name for field in fields(RepairInputs)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"Unknown input field(s): {', '.join(unknown)}")
    return RepairInputs(**data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Calculate a Type A composite pipe repair using the included ISO 24817:2017-based model."
    )
    parser.add_argument("--input", type=Path, default=Path("example_input.json"),
                        help="JSON input file (default: example_input.json)")
    parser.add_argument("--format", choices=("text", "json"), default="text",
                        help="Output format (default: text)")
    parser.add_argument("--output", type=Path, help="Save calculation output to a file")
    args = parser.parse_args()

    try:
        inputs = load_inputs(args.input)
        result = calculate_repair(inputs)
        if args.format == "json":
            rendered = json.dumps(result, indent=2, ensure_ascii=False, default=str)
        else:
            buffer = StringIO()
            with redirect_stdout(buffer):
                print_report(result)
            rendered = buffer.getvalue()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + ("\n" if args.format == "json" else ""), encoding="utf-8")
            print(f"Report saved: {args.output}")
        else:
            print(rendered)
        return 0
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
