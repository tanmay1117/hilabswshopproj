#!/usr/bin/env python3
"""
run_all.py — Batch evaluator for all charts in test_data/
==========================================================
Runs test.py on every JSON file found under the data directory
and stores results in output/.

Usage:
    python run_all.py [--data-dir PATH] [--output-dir PATH] [--api-key KEY]

Environment:
    OPENROUTER_API_KEY   — API key (alternative to --api-key flag)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Batch evaluator for all charts")
    parser.add_argument("--data-dir",   default="workshop_test_data",
                        help="Root directory containing chart sub-folders")
    parser.add_argument("--output-dir", default="output",
                        help="Directory to write evaluation JSON files")
    parser.add_argument("--api-key",    metavar="KEY",
                        help="OpenRouter API key (overrides OPENROUTER_API_KEY)")
    args = parser.parse_args()

    data_dir   = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("ERROR: OpenRouter API key required.\n"
              "  Set OPENROUTER_API_KEY env var  OR  pass --api-key KEY",
              file=sys.stderr)
        sys.exit(1)

    # Collect all JSON files
    json_files = sorted(data_dir.rglob("*.json"))
    if not json_files:
        print(f"ERROR: No JSON files found under {data_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"\nFound {len(json_files)} chart files under '{data_dir}'")
    print(f"Output directory: '{output_dir}'\n")

    success, failed = 0, []

    for i, json_file in enumerate(json_files, 1):
        md_file     = json_file.with_suffix(".md")
        output_file = output_dir / json_file.name

        print(f"[{i:02d}/{len(json_files)}] {json_file.name}")

        cmd = [
            sys.executable, "test.py",
            str(json_file),
            str(output_file),
            "--api-key", api_key,
        ]
        if md_file.exists():
            cmd += ["--md", str(md_file)]

        result = subprocess.run(cmd, capture_output=False)

        if result.returncode == 0:
            success += 1
            print(f"          ✓ Done → {output_file}")
        else:
            failed.append(json_file.name)
            print(f"          ✗ FAILED (exit {result.returncode})")

    print(f"\n{'='*50}")
    print(f"  Completed: {success}/{len(json_files)}")
    if failed:
        print(f"  Failed:    {len(failed)}")
        for f in failed:
            print(f"             - {f}")
    print(f"{'='*50}\n")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
