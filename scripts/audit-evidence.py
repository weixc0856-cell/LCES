#!/usr/bin/env python3
"""Fail when uploaded evidence contains secrets or user-home paths (P2.3-E).

Usage::

    uv run python scripts/audit-evidence.py motion-evidence

Exit codes: 0 clean, 1 findings, 2 the root is not a directory. No third-party
dependency is involved; the scan logic lives in ``content_studio.evidence_audit``
and is covered by unit tests.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from content_studio.evidence_audit import audit_evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path, help="evidence directory to scan")
    args = parser.parse_args()
    if not args.root.is_dir():
        print(f"FAIL {args.root} is not a directory")
        return 2
    findings = audit_evidence(args.root)
    for finding in findings:
        print(f"FAIL {finding.line_text()}")
    print(f"{len(findings)} finding(s) in {args.root}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
