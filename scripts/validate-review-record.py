"""Read-only validation of a structured evidence review record.

It checks the project links (source, chunk, claim, paper element) and prints the
three separate states: program status, research finding, human conclusion.
It never signs or modifies a review.

Usage::

    uv run python scripts/validate-review-record.py projects/attention-is-all-you-need
"""

from __future__ import annotations

import argparse
from pathlib import Path

from content_studio.structured_review import (
    default_review_path,
    load_review,
    validate_review_links,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--review-file", type=Path, default=None)
    args = parser.parse_args()

    project = args.project_dir.resolve()
    path = args.review_file or default_review_path(project)
    document = load_review(path)
    validate_review_links(project, document)

    print(f"review: {path}")
    print(f"items: {len(document.items)} | status: {document.status}")
    for item in document.items:
        findings = (
            ",".join(
                sorted(
                    {verification.research_finding for verification in item.research_verification}
                )
            )
            or "-"
        )
        signed = (
            ",".join(
                sorted(
                    {
                        str(verification.reviewed_by_human)
                        for verification in item.research_verification
                    }
                )
            )
            or "-"
        )
        substantive = (
            f"{item.substantive_review.reviewer_kind}:{item.substantive_review.finding}"
            f"({','.join(item.substantive_review.scopes)})"
            if item.substantive_review is not None
            else "-"
        )
        print(
            f"- {item.review_id}: program={item.program_status}/{item.program_reason} | "
            f"research={findings} | reviewed_by_human={signed} | "
            f"ai_substantive={substantive} | human={item.conclusion}"
        )
    pending = sum(1 for item in document.items if item.conclusion == "pending")
    print(f"pending human conclusions: {pending}/{len(document.items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
