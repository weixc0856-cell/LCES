# ruff: noqa: E501
"""Build the human review packet for the course project.

The packet is a read-only bundle for a human reviewer: evidence packets,
source checks, the candidate course, visual review and
audit reports. It is deliberately *not* a release.

Design rules enforced here (they are the P6 defects turned into checks):

- every relative Markdown link in the packet must resolve inside the packet;
- the commands file is native PowerShell (no ``VAR=value command``);
- every file gets a SHA-256 entry;
- a ``.7z`` archive is produced when 7-Zip is available, next to the ``.zip``.

Usage:
    python scripts/build-review-packet.py \
        --project projects/attention-is-all-you-need \
        --design docs/design/p6 \
        --report docs/design/p7/p7-execution-2026-10-24.md \
        --out var/handoff/LECS-P7-人工核验包-2026-10-24
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REWRITES = {
    "evidence-packets/index.md": "02-evidence/index.md",
    "../p6/evidence-packets/index.md": "02-evidence/index.md",
    "content-snapshot/manifest.json": "07-audits/snapshot-manifest.json",
    "source-dispute-review-2026-10-24.md": "03-source-check/source-dispute-review.md",
    "../p6/source-dispute-review-2026-10-24.md": "03-source-check/source-dispute-review.md",
    "course-content-review-2026-10-24.md": "04-course/course-content-review.md",
    "visual-review-2026-10-24.md": "06-visual/visual-review.md",
    "../p6/visual-review-2026-10-24.md": "06-visual/visual-review.md",
    "../evidence-remediation-2026-10-24.json": "03-source-check/evidence-remediation.json",
    "../../evidence-remediation-2026-10-24.json": "03-source-check/evidence-remediation.json",
    "hash-lineage-2026-10-24.md": "07-audits/hash-lineage.md",
    "timing-audio-2026-10-24.md": "07-audits/timing-audio/timing-audio.md",
    "timing-audio-2026-10-24.json": "07-audits/timing-audio/timing-audio.json",
    "../p6/timing-audio-2026-10-24.md": "07-audits/timing-audio/timing-audio.md",
}

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
UNIX_ENV = re.compile(r"^\s*[A-Z_][A-Z0-9_]*=\S+\s+\S", re.MULTILINE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def copy(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise SystemExit(f"missing input: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def rewrite(src: Path, dst: Path, replacements: dict[str, str]) -> None:
    text = src.read_text(encoding="utf-8")
    # One pass, longest key first: "../p6/evidence-packets/..." must win over
    # the bare "evidence-packets/..." that is its suffix, and a replacement
    # must never be rewritten twice.
    pattern = re.compile(
        "|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True))
    )
    text = pattern.sub(lambda match: replacements[match.group(0)], text)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")


def check_links(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(root.rglob("*.md")):
        for match in LINK.finditer(path.read_text(encoding="utf-8")):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            candidate = (path.parent / target).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                problems.append(f"{path.relative_to(root)}: link escapes the packet: {target}")
                continue
            if not candidate.exists():
                problems.append(f"{path.relative_to(root)}: broken link: {target}")
    return problems


def check_commands(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems = (
        [f"Unix-style environment assignment: {line.strip()}" for line in UNIX_ENV.findall(text)]
        if UNIX_ENV.search(text)
        else []
    )
    return problems


def build(args: argparse.Namespace) -> int:
    project = (ROOT / args.project).resolve()
    design = (ROOT / args.design).resolve()
    report = (ROOT / args.report).resolve()
    out = (ROOT / args.out).resolve()
    course_review = (
        (ROOT / args.course_review).resolve()
        if args.course_review
        else (design / "course-content-review-2026-10-24.md")
    )
    hash_lineage = (
        (ROOT / args.hash_lineage).resolve()
        if args.hash_lineage
        else (design / "hash-lineage-2026-10-24.md")
    )
    snapshot = (
        (ROOT / args.snapshot).resolve()
        if args.snapshot
        else (design / "content-snapshot" / "manifest.json")
    )
    evidence_dir = (
        (ROOT / args.evidence_dir).resolve() if args.evidence_dir else (design / "evidence-packets")
    )
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    (out / "00-先读我.md").write_text(
        f"""# LECS 人工核验包（{args.date}）

这是给**人类审核者/产品负责人**的本地核验包，不是发布物。

- 生成器：`scripts/build-review-packet.py`；生成时间：{args.date}
- 项目：`{args.project}`
- 课程契约：见 `04-course/course_contract.json`（状态以文件为准）
- 证据复核：**14 项 pending**；没有人工签署
- 视觉：**10/10 pending**；没有自动批准基线
- 源文本哈希口径见 `07-audits/hash-lineage.md`；计时音频见 `07-audits/timing-audio/`

## 建议核验顺序

1. `01-执行报告.md`
2. `02-evidence/`：逐条核对后签署
3. `03-source-check/`：来源冲突、主张、公式与表格
4. `04-course/`：14 节课程、契约、内容审读
5. `06-visual/`：10 张截图与基线
6. `07-audits/`：审计、计时、快照哈希、哈希口径
7. `04-commands.md`：PowerShell 命令模板（在仓库根目录执行）

## 边界

- 不要在没有核对原文的情况下签署；不要用 AI 结论代替你的签名。
- 不要修改 `release/`；不要在本包基础上直接发布。
- 计时音频是 TTS 实测朗读时长，不是学习者完成时长。
- `04-course/speaker_script.INTERNAL.md` 是内部口播稿，不要公开。
""",
        encoding="utf-8",
    )

    checklist = [
        ["序号", "类别", "核验项", "需要决定/动作", "状态", "备注"],
        [
            "1",
            "产品契约",
            "14 节 / 20 分钟 / 16:9 deck + 阅读版",
            "批准或修改",
            "待办",
            "契约 v1.1 draft",
        ],
        ["2", "证据", "14 项证据复核记录", "逐条核对后签署", "待办", "含 41.0/41.8 冲突项"],
        ["3", "来源", "EN-FR 41.0 / 41.8", "裁决并 --conflict-ack", "待办", "禁止自动裁决"],
        [
            "4",
            "内容",
            "Table 1/2/3/4 与公式",
            "核对列语义与公式",
            "待办",
            "Table 3 (C) 行需重点确认",
        ],
        ["5", "渲染", "16:9 deck 与离线公式", "在目标机器上确认", "待办", "无 CDN、无外部字体"],
        ["6", "试测", "真实学习者执行", "执行后填写结果", "未执行", "禁止模拟数据"],
        ["7", "视觉", "10 张截图/基线", "逐项确认后更新", "待办", "当前 10/10 pending"],
        ["8", "计时", "重新录制并计时", "内容变更后必须重测", "待办", "旧音频对应旧口播稿"],
        ["9", "验收", "Gate B", "accept-course（真人）", "待办", "需先完成 1–8"],
        ["10", "发布", "v2", "approve/release/release-check", "未开始", "需先完成 9"],
    ]
    with (out / "01-核验清单.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(checklist)

    rewrite(report, out / "01-执行报告.md", REWRITES)
    if course_review.is_file():
        copy(course_review, out / "04-course/course-content-review.md")
    if hash_lineage.is_file():
        copy(hash_lineage, out / "07-audits/hash-lineage.md")
    for name, target in (
        ("source-dispute-review-2026-10-24.md", "03-source-check/source-dispute-review.md"),
        ("timing-audio-2026-10-24.md", "07-audits/timing-audio/timing-audio.md"),
    ):
        if (design / name).is_file():
            copy(design / name, out / target)

    for item in sorted(evidence_dir.iterdir()):
        if item.is_file():
            copy(item, out / "02-evidence" / item.name)
    copy(
        design / "source-dispute-review-2026-10-24.md",
        out / "03-source-check/source-dispute-review.md",
    )
    evidence_remediation = design.parent / "evidence-remediation-2026-10-24.json"
    if evidence_remediation.is_file():
        copy(evidence_remediation, out / "03-source-check/evidence-remediation.json")
    for name in (
        "internal/sources/source-001.txt",
        "internal/source_map.json",
        "internal/claims.json",
        "internal/evidence_ledger.csv",
        "internal/qa/structured_evidence_review.json",
    ):
        copy(project / name, out / "03-source-check" / Path(name).name)

    course_files = {
        "content/public_content.json": "public_content.json",
        "content/reading_edition.json": "reading_edition.json",
        "content/outline.json": "outline.json",
        "internal/plan/course_contract.json": "course_contract.json",
        "internal/plan/course_guards.json": "course_guards.json",
        # Internal narration keeps its explicit INTERNAL marker in the packet.
        "internal/speaker_script.md": "speaker_script.INTERNAL.md",
        "build/slides/index.html": "build/slides/index.html",
        "build/reading_edition.html": "build/reading_edition.html",
    }
    for name, target in course_files.items():
        copy(project / name, out / "04-course" / target)

    rewrite(
        design / "visual-review-2026-10-24.md",
        out / "06-visual/visual-review.md",
        {"internal/qa/screenshots/": "screenshots/", "internal/qa/baselines/": "baselines/"},
    )
    copy(design / "visual-review-2026-10-24.json", out / "06-visual/visual-review.json")
    for item in (project / "internal/qa/screenshots").iterdir():
        if item.is_file():
            copy(item, out / "06-visual/screenshots" / item.name)
    for item in (project / "internal/qa/baselines").iterdir():
        if item.is_file():
            copy(item, out / "06-visual/baselines" / item.name)

    for name in (
        "internal/qa/course_content_audit.json",
        "internal/qa/course_quality_audit.json",
        "internal/qa/timing_evidence.json",
        "internal/qa/qa_report.json",
    ):
        copy(project / name, out / "07-audits" / Path(name).name)
    copy(snapshot, out / "07-audits/snapshot-manifest.json")
    rewrite(
        design / "timing-audio-2026-10-24.md",
        out / "07-audits/timing-audio/timing-audio.md",
        {"timing-audio-2026-10-24.json": "timing-audio.json"},
    )
    copy(design / "timing-audio-2026-10-24.json", out / "07-audits/timing-audio/timing-audio.json")
    copy(project / "var/timing/narration.mp3", out / "07-audits/timing-audio/narration.mp3")

    (out / "04-commands.md").write_text(
        """# 核验与签署命令（Windows PowerShell）

> 在仓库根目录执行。`--by` 必须填真实审核者；不要使用 AI 身份。
> 参数以当前仓库的 `--help` 为准：`project_dir` 是位置参数，不是 `--project-dir`。

```powershell
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$Project = "projects/attention-is-all-you-need"

# 0) 只读：查看复核记录状态
.\\.venv\\Scripts\\python.exe scripts\\validate-review-record.py $Project

# 1) 重新构建、审计与自动门禁
.\\.venv\\Scripts\\lces.exe build $Project
.\\.venv\\Scripts\\lces.exe audit-course $Project
.\\.venv\\Scripts\\lces.exe validate $Project

# 2) 逐条签署证据（把占位符换成真实信息；冲突项必须 --conflict-ack）
$Reviewer = "<真实审核者>"
$Basis = "<核对原文后的依据>"
$ReviewIds = @(
  "review-formula-attention", "review-formula-multihead", "review-formula-positional",
  "review-formula-postln", "review-formula-variance", "review-formula-ffn", "review-formula-noam",
  "review-table2-base-27.3", "review-table2-big-ende-28.4", "review-table2-big-enfr-conflict",
  "review-table2-rows", "review-table3-base-25.8", "review-table3-big-26.4", "review-table3-ablation"
)
foreach ($ReviewId in $ReviewIds) {
  .\\.venv\\Scripts\\lces.exe review-evidence $Project --review-id $ReviewId --by $Reviewer --conclusion pass --basis $Basis
}
# 冲突项单独执行（必须显式确认已披露 41.0 与 41.8）
.\\.venv\\Scripts\\lces.exe review-evidence $Project --review-id review-table2-big-enfr-conflict --by $Reviewer --conclusion pass --conflict-ack --basis "已核实 arXiv:1706.03762v7 Table 2 (41.8) 与 §6.1 / NeurIPS (41.0) 双版本披露"

# 3) 批准课程契约（产品负责人）
.\\.venv\\Scripts\\lces.exe approve-course-contract $Project --by "<产品负责人>" --notes "确认 14 节、20 分钟、16:9 deck + 阅读版"

# 4) 重新计时（内容变更后旧音频作废），再完成 Gate B 人工验收
.\\.venv\\Scripts\\lces.exe accept-course $Project --by "<验收人>" --decision pass --timing-confirmed --visual-confirmed --checks-confirmed

# 5) 重新审计与发布检查（发布仍需单独授权）
.\\.venv\\Scripts\\lces.exe audit-product $Project
.\\.venv\\Scripts\\lces.exe release-check $Project --version v1
```
""",
        encoding="utf-8",
    )

    problems = check_links(out) + check_commands(out / "04-commands.md")
    if problems:
        for problem in problems:
            print(f"PACKET ERROR: {problem}", file=sys.stderr)
        return 1

    entries = []
    for item in sorted(out.rglob("*")):
        if item.is_file() and item.name != "PACKAGE-SHA256.txt":
            entries.append(f"{sha256(item)}  {item.relative_to(out).as_posix()}")
    (out / "PACKAGE-SHA256.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")

    zip_path = out.with_suffix(".zip")
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for item in sorted(out.rglob("*")):
            if item.is_file():
                archive.write(item, (Path(out.name) / item.relative_to(out)).as_posix())

    program_files = os.environ.get("ProgramFiles", "")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
    candidates = [
        shutil.which("7z"),
        shutil.which("7za"),
        str(Path(program_files) / "7-Zip" / "7z.exe") if program_files else "",
        str(Path(program_files_x86) / "7-Zip" / "7z.exe") if program_files_x86 else "",
    ]
    seven_zip = next((item for item in candidates if item and Path(item).is_file()), None)
    if seven_zip:
        archive_path = out.with_suffix(".7z")
        subprocess.run(
            [seven_zip, "a", "-t7z", "-mx=9", str(archive_path), str(out.name)],
            cwd=out.parent,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        print("7z", archive_path, archive_path.stat().st_size)

    print("packet", out)
    print("files", sum(1 for item in out.rglob("*") if item.is_file()))
    print("zip", zip_path, zip_path.stat().st_size)
    print("zip sha256", sha256(zip_path))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--design", default="docs/design/p6")
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--course-review", default="")
    parser.add_argument("--hash-lineage", default="")
    parser.add_argument("--snapshot", default="")
    parser.add_argument("--evidence-dir", default="")
    parser.add_argument("--date", default="2026-10-24")
    return build(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
