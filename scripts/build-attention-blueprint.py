"""One-off builder for the Attention Is All You Need course blueprint.

Writes three checked-in artifacts under the project's ``internal/`` tree:

* ``internal/plan/paper_map.json``
* ``internal/plan/coverage_matrix.json``
* ``internal/course_master.json``

The blueprint is planning data only: every unit is ``planned`` with an empty
body, and every paper element stays ``unverified`` until a human or the
sectioned-research stage records evidence. Run with ``uv run python`` from the
repository root.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from content_studio.models import (
    CourseChapter,
    CourseMaster,
    CoverageEntry,
    CoverageMatrix,
    LearningUnit,
    PaperElement,
    PaperMap,
)
from content_studio.utils import write_json

PROJECT = Path("projects/attention-is-all-you-need")
PLAN_DIR = PROJECT / "internal" / "plan"
# The blueprint is hand-authored design data, so the canonical copy is a
# tracked fixture (project workspaces are git-ignored). The same bytes are
# copied into the project for the trial run.
FIXTURE_DIR = Path("tests/fixtures/course_plan/attention")
GENERATED_AT = "2026-10-23T00:00:00Z"


def element(
    item_id: str,
    kind: str,
    title: str,
    locator: str,
    *,
    required: bool = True,
    status: str = "unverified",
    notes: str = "",
) -> PaperElement:
    return PaperElement(
        paper_item_id=item_id,
        kind=kind,  # type: ignore[arg-type]
        title=title,
        locator=locator,
        required=required,
        status=status,  # type: ignore[arg-type]
        notes=notes,
    )


def unit(
    unit_id: str,
    chapter_id: str,
    title: str,
    unit_type: str,
    minutes: float,
    *,
    objectives: list[str],
    concepts: list[str],
    paper_items: list[str],
    visuals: list[str] | None = None,
    prerequisites: list[str] | None = None,
) -> LearningUnit:
    return LearningUnit(
        unit_id=unit_id,
        chapter_id=chapter_id,
        title=title,
        unit_type=unit_type,  # type: ignore[arg-type]
        objectives=objectives,
        prerequisites=prerequisites or [],
        key_concepts=concepts,
        paper_item_ids=paper_items,
        visual_requirements=visuals or [],
        estimated_minutes=minutes,
        status="planned",
    )


PAPER_ELEMENTS = [
    element("paper-001", "section", "摘要：研究问题与报告结果", "Abstract"),
    element("paper-002", "section", "引言：序列建模的瓶颈与本文贡献", "§1"),
    element("paper-003", "section", "相关工作：RNN、CNN 与注意力", "§2", required=False),
    element("paper-004", "section", "模型总体架构", "§3"),
    element("paper-005", "section", "编码器与解码器堆叠", "§3.1"),
    element("paper-006", "section", "缩放点积注意力", "§3.2.1"),
    element("paper-007", "equation", "注意力公式与缩放因子", "§3.2.1 公式"),
    element("paper-008", "section", "多头注意力", "§3.2.2"),
    element("paper-009", "equation", "多头注意力的投影与拼接公式", "§3.2.2 公式"),
    element("paper-010", "section", "注意力在本模型中的三种用法", "§3.2.3"),
    element("paper-011", "section", "逐位置前馈网络", "§3.3"),
    element("paper-012", "section", "词嵌入与 Softmax", "§3.4"),
    element("paper-013", "section", "位置编码", "§3.5"),
    element("paper-014", "equation", "正弦位置编码公式", "§3.5 公式"),
    element("paper-015", "section", "为什么选择自注意力", "§4"),
    element("paper-016", "table", "Table 1：各层类型的复杂度与路径长度", "§4 Table 1"),
    element("paper-017", "figure", "Figure 1：Transformer 架构图", "§3 Figure 1"),
    element(
        "paper-018",
        "figure",
        "Figure 2：注意力可视化",
        "§3.2.3 Figure 2",
        required=False,
    ),
    element("paper-019", "section", "训练设置总览", "§5"),
    element("paper-020", "experiment", "训练数据与批处理", "§5.1"),
    element("paper-021", "experiment", "硬件与训练时间表", "§5.2"),
    element("paper-022", "experiment", "优化器与学习率调度", "§5.3"),
    element("paper-023", "experiment", "正则化（残差 dropout、标签平滑）", "§5.4"),
    element("paper-024", "result", "WMT 2014 机器翻译结果", "§6.1"),
    element("paper-025", "table", "Table 2：BLEU 与训练成本对比", "§6.1 Table 2"),
    element("paper-026", "ablation", "模型变体（Table 3）", "§6.2"),
    element("paper-027", "table", "Table 3：模型变体结果", "§6.2 Table 3"),
    element("paper-028", "experiment", "英语成分句法分析", "§6.3"),
    element("paper-029", "conclusion", "结论与后续影响", "§7"),
    element(
        "paper-030",
        "limitation",
        "局限与适用边界",
        "无独立章节",
        status="not_found",
        notes=(
            "论文没有独立的 Limitations 章节；课程须从 §4 复杂度讨论与 §6.2 变体结果归纳，"
            "并明确标注为课程解释。"
        ),
    ),
]

UNITS = [
    # 01 问题与目标
    unit(
        "unit-001",
        "chapter-001",
        "问题背景：RNN/CNN 序列建模的瓶颈",
        "concept",
        3,
        objectives=["解释论文要解决的序列转换问题", "说明循环与卷积架构的顺序依赖"],
        concepts=["序列到序列学习", "顺序计算", "长距离依赖"],
        paper_items=["paper-002"],
    ),
    unit(
        "unit-002",
        "chapter-001",
        "课程导览与学习目标",
        "concept",
        3,
        objectives=["说明课程范围与阅读顺序", "区分论文事实、作者解释与课程解释"],
        concepts=["课程范围", "资料类型", "证据标记"],
        paper_items=["paper-001"],
    ),
    # 02 相关工作
    unit(
        "unit-003",
        "chapter-002",
        "相关工作：注意力如何进入序列模型",
        "concept",
        3,
        objectives=["说明注意力在本文之前的用法", "指出本文与既有工作的差异"],
        concepts=["RNN", "CNN", "注意力机制"],
        paper_items=["paper-003"],
    ),
    unit(
        "unit-004",
        "chapter-002",
        "设计动机：并行性、路径长度与可学习性",
        "concept",
        3,
        objectives=["解释选择自注意力的三条动机", "说明动机与架构选择的关系"],
        concepts=["并行计算", "路径长度", "归纳偏置"],
        paper_items=["paper-002", "paper-015"],
    ),
    # 03 贡献
    unit(
        "unit-005",
        "chapter-003",
        "论文贡献清单与全文路线",
        "concept",
        3,
        objectives=["列出架构、训练与实验结果三类贡献", "建立后续章节的阅读地图"],
        concepts=["贡献分类", "论文结构"],
        paper_items=["paper-001", "paper-002"],
    ),
    # 04 总体架构
    unit(
        "unit-006",
        "chapter-004",
        "编码器—解码器总体数据流",
        "concept",
        5,
        objectives=["描述输入到输出的完整路径", "解释编码器与解码器的分工"],
        concepts=["编码器堆叠", "解码器堆叠", "自回归生成"],
        paper_items=["paper-004", "paper-005", "paper-017"],
        visuals=["SVG 架构图：编码器/解码器、子层与数据流"],
    ),
    unit(
        "unit-007",
        "chapter-004",
        "子层连接：残差、层归一化与前馈网络",
        "concept",
        3,
        objectives=["说明每个子层的组成", "解释残差与层归一化的作用"],
        concepts=["残差连接", "层归一化", "逐位置前馈网络", "嵌入与 Softmax"],
        paper_items=["paper-011", "paper-012"],
    ),
    # 05 注意力
    unit(
        "unit-008",
        "chapter-005",
        "Query、Key、Value 的直觉与来源",
        "concept",
        3,
        objectives=["解释 Q/K/V 各自承担的角色", "说明它们如何由同一输入线性投影得到"],
        concepts=["Query", "Key", "Value", "线性投影"],
        paper_items=["paper-006"],
    ),
    unit(
        "unit-009",
        "chapter-005",
        "缩放点积公式与数值演算",
        "formula",
        5,
        objectives=["逐项解释公式", "用一个 3×3 的小例子完成一次完整演算"],
        concepts=["点积相似度", "缩放因子", "Softmax", "加权求和"],
        paper_items=["paper-006", "paper-007"],
        visuals=["公式分步揭示：QKᵀ → 缩放 → Softmax → 乘 V"],
    ),
    unit(
        "unit-010",
        "chapter-005",
        "掩码与 Softmax 的作用",
        "formula",
        3,
        objectives=["说明 padding mask 与 causal mask 的区别", "解释掩码如何改变权重"],
        concepts=["Padding mask", "Causal mask", "负无穷填充"],
        paper_items=["paper-006", "paper-010"],
    ),
    # 06 多头
    unit(
        "unit-011",
        "chapter-006",
        "多头的拆分、并行计算、拼接与投影",
        "formula",
        4,
        objectives=["解释多头如何拆分与合并", "核对张量维度变化"],
        concepts=["头维度", "拼接", "输出投影"],
        paper_items=["paper-008", "paper-009"],
        visuals=["张量维度示意图 + 分步动画"],
    ),
    unit(
        "unit-012",
        "chapter-006",
        "多头与单头的区别及三种应用位置",
        "comparison",
        3,
        objectives=["比较多头与单头的表示能力", "说明三种注意力用法"],
        concepts=["表示子空间", "编码器—解码器注意力", "自注意力"],
        paper_items=["paper-008", "paper-010"],
    ),
    # 07 位置编码
    unit(
        "unit-013",
        "chapter-007",
        "正弦位置编码公式",
        "formula",
        4,
        objectives=["解释公式中每一项", "说明不同频率的作用"],
        concepts=["正弦/余弦", "频率", "绝对位置"],
        paper_items=["paper-013", "paper-014"],
        visuals=["位置编码热力图（程序化生成）"],
    ),
    unit(
        "unit-014",
        "chapter-007",
        "为什么需要位置信息",
        "concept",
        2,
        objectives=["说明自注意力的排列等变性", "解释无位置编码时丢失了什么"],
        concepts=["排列等变", "顺序信息"],
        paper_items=["paper-013"],
    ),
    # 08 训练机制
    unit(
        "unit-015",
        "chapter-008",
        "子层连接与因果掩码",
        "concept",
        4,
        objectives=["说明解码器为何需要遮蔽未来位置", "检查训练与推理的差异"],
        concepts=["因果掩码", "teacher forcing", "自回归推理"],
        paper_items=["paper-005", "paper-010"],
    ),
    unit(
        "unit-016",
        "chapter-008",
        "训练目标与推理流程",
        "concept",
        3,
        objectives=["说明交叉熵目标", "描述推理解码过程"],
        concepts=["交叉熵", "共享嵌入", "beam search"],
        paper_items=["paper-012"],
    ),
    # 09 训练设置
    unit(
        "unit-017",
        "chapter-009",
        "数据、批处理与硬件",
        "experiment",
        3,
        objectives=["复述训练数据与批大小", "说明硬件与训练时长"],
        concepts=["WMT 2014", "batch size", "8×P100"],
        paper_items=["paper-019", "paper-020", "paper-021"],
    ),
    unit(
        "unit-018",
        "chapter-009",
        "优化器与正则化",
        "experiment",
        3,
        objectives=["说明 Adam 参数与 warmup", "说明 dropout 与标签平滑"],
        concepts=["Adam", "warmup", "dropout", "label smoothing"],
        paper_items=["paper-022", "paper-023"],
    ),
    # 10 实验结果
    unit(
        "unit-019",
        "chapter-010",
        "WMT 2014 实验设计与评价指标",
        "experiment",
        3,
        objectives=["说明任务、数据与 BLEU", "识别可比较与不可比较的基线"],
        concepts=["EN-DE", "EN-FR", "BLEU", "基线"],
        paper_items=["paper-024"],
    ),
    unit(
        "unit-020",
        "chapter-010",
        "Table 2 结果解读",
        "experiment",
        4,
        objectives=["解释 28.4 / 41.8 BLEU 的含义", "限定结论的适用范围"],
        concepts=["BLEU 对比", "训练成本", "集成模型"],
        paper_items=["paper-024", "paper-025", "paper-001"],
        visuals=["Vega-Lite 柱状图：Transformer 与基线 BLEU 对比"],
    ),
    unit(
        "unit-021",
        "chapter-010",
        "英语成分句法分析",
        "experiment",
        2,
        objectives=["说明该任务的设置与结果", "判断它支持哪条泛化结论"],
        concepts=["WSJ", "半监督设置", "F1"],
        paper_items=["paper-028"],
    ),
    # 11 变体、消融与复杂度
    unit(
        "unit-022",
        "chapter-011",
        "Table 3 模型变体与消融",
        "experiment",
        4,
        objectives=["逐项解释变体如何影响 BLEU", "区分单变量改动与组合改动"],
        concepts=["头数", "维度", "dropout", "位置编码变体"],
        paper_items=["paper-026", "paper-027"],
        visuals=["Vega-Lite 表格或点图：变体与 BLEU 变化"],
    ),
    unit(
        "unit-023",
        "chapter-011",
        "复杂度、路径长度与并行性",
        "comparison",
        3,
        objectives=["比较自注意力、循环层与卷积层", "说明序列长度增长时的成本"],
        concepts=["每层复杂度", "最小路径长度", "并行操作数"],
        paper_items=["paper-015", "paper-016"],
        visuals=["Table 1 重排版 + 复杂度曲线"],
    ),
    # 12 结论与边界
    unit(
        "unit-024",
        "chapter-012",
        "论文结论、局限与后续影响",
        "concept",
        3,
        objectives=["区分论文结论与后续影响", "列出论文未回答的问题"],
        concepts=["结论边界", "外部补充", "后续研究"],
        paper_items=["paper-029", "paper-030"],
    ),
    unit(
        "unit-025",
        "chapter-012",
        "复现清单与讨论问题",
        "application",
        2,
        objectives=["列出复现所需的关键配置", "提出可继续验证的问题"],
        concepts=["复现清单", "开放问题"],
        paper_items=["paper-019", "paper-022", "paper-023"],
    ),
]

CHAPTERS = [
    CourseChapter(
        chapter_id="chapter-001",
        title="课程导览与问题定义",
        objectives=["说明论文要解决的问题", "建立课程学习路径"],
        unit_ids=["unit-001", "unit-002"],
    ),
    CourseChapter(
        chapter_id="chapter-002",
        title="研究背景与设计动机",
        objectives=["理解序列建模的既有路线", "说明本文的设计动机"],
        unit_ids=["unit-003", "unit-004"],
    ),
    CourseChapter(
        chapter_id="chapter-003",
        title="论文的核心贡献",
        objectives=["区分架构、训练与实验贡献"],
        unit_ids=["unit-005"],
    ),
    CourseChapter(
        chapter_id="chapter-004",
        title="Transformer 总体架构",
        objectives=["描述整体数据流", "解释子层组成"],
        unit_ids=["unit-006", "unit-007"],
    ),
    CourseChapter(
        chapter_id="chapter-005",
        title="Scaled Dot-Product Attention",
        objectives=["解释 Q/K/V", "完成数值演算", "说明掩码作用"],
        unit_ids=["unit-008", "unit-009", "unit-010"],
    ),
    CourseChapter(
        chapter_id="chapter-006",
        title="Multi-Head Attention",
        objectives=["说明多头计算", "比较单头与多头"],
        unit_ids=["unit-011", "unit-012"],
    ),
    CourseChapter(
        chapter_id="chapter-007",
        title="位置编码与顺序信息",
        objectives=["解释位置编码公式", "说明顺序信息的必要性"],
        unit_ids=["unit-013", "unit-014"],
    ),
    CourseChapter(
        chapter_id="chapter-008",
        title="编码器、解码器与训练机制",
        objectives=["解释因果掩码", "区分训练与推理"],
        unit_ids=["unit-015", "unit-016"],
    ),
    CourseChapter(
        chapter_id="chapter-009",
        title="训练设置",
        objectives=["复述数据、硬件与优化配置"],
        unit_ids=["unit-017", "unit-018"],
    ),
    CourseChapter(
        chapter_id="chapter-010",
        title="实验设计与结果",
        objectives=["解释实验设置", "解读 Table 2", "判断结论边界"],
        unit_ids=["unit-019", "unit-020", "unit-021"],
    ),
    CourseChapter(
        chapter_id="chapter-011",
        title="模型变体、消融与复杂度",
        objectives=["解读 Table 3", "比较不同层类型的成本"],
        unit_ids=["unit-022", "unit-023"],
    ),
    CourseChapter(
        chapter_id="chapter-012",
        title="贡献、局限与总结",
        objectives=["区分论文结论与后续影响", "形成复现与讨论清单"],
        unit_ids=["unit-024", "unit-025"],
    ),
]

COVERAGE = [
    CoverageEntry(
        paper_item_id="paper-001",
        covered_by=["unit-002", "unit-005", "unit-020"],
        status="covered",
        notes="摘要中的问题与结果分别在贡献清单与结果解读中讲解。",
    ),
    CoverageEntry(
        paper_item_id="paper-002", covered_by=["unit-001", "unit-004", "unit-005"], status="covered"
    ),
    CoverageEntry(
        paper_item_id="paper-003",
        required=False,
        covered_by=["unit-003"],
        status="covered",
    ),
    CoverageEntry(paper_item_id="paper-004", covered_by=["unit-006"], status="covered"),
    CoverageEntry(paper_item_id="paper-005", covered_by=["unit-006", "unit-015"], status="covered"),
    CoverageEntry(
        paper_item_id="paper-006", covered_by=["unit-008", "unit-009", "unit-010"], status="covered"
    ),
    CoverageEntry(paper_item_id="paper-007", covered_by=["unit-009"], status="covered"),
    CoverageEntry(paper_item_id="paper-008", covered_by=["unit-011", "unit-012"], status="covered"),
    CoverageEntry(paper_item_id="paper-009", covered_by=["unit-011"], status="covered"),
    CoverageEntry(
        paper_item_id="paper-010", covered_by=["unit-010", "unit-012", "unit-015"], status="covered"
    ),
    CoverageEntry(paper_item_id="paper-011", covered_by=["unit-007"], status="covered"),
    CoverageEntry(paper_item_id="paper-012", covered_by=["unit-007", "unit-016"], status="covered"),
    CoverageEntry(paper_item_id="paper-013", covered_by=["unit-013", "unit-014"], status="covered"),
    CoverageEntry(paper_item_id="paper-014", covered_by=["unit-013"], status="covered"),
    CoverageEntry(paper_item_id="paper-015", covered_by=["unit-004", "unit-023"], status="covered"),
    CoverageEntry(paper_item_id="paper-016", covered_by=["unit-023"], status="covered"),
    CoverageEntry(paper_item_id="paper-017", covered_by=["unit-006"], status="covered"),
    CoverageEntry(
        paper_item_id="paper-018",
        required=False,
        status="not_applicable",
        notes="注意力可视化为可选素材，不单独承担教学单元。",
    ),
    CoverageEntry(paper_item_id="paper-019", covered_by=["unit-017", "unit-025"], status="covered"),
    CoverageEntry(paper_item_id="paper-020", covered_by=["unit-017"], status="covered"),
    CoverageEntry(paper_item_id="paper-021", covered_by=["unit-017"], status="covered"),
    CoverageEntry(paper_item_id="paper-022", covered_by=["unit-018", "unit-025"], status="covered"),
    CoverageEntry(paper_item_id="paper-023", covered_by=["unit-018", "unit-025"], status="covered"),
    CoverageEntry(paper_item_id="paper-024", covered_by=["unit-019", "unit-020"], status="covered"),
    CoverageEntry(paper_item_id="paper-025", covered_by=["unit-020"], status="covered"),
    CoverageEntry(paper_item_id="paper-026", covered_by=["unit-022"], status="covered"),
    CoverageEntry(paper_item_id="paper-027", covered_by=["unit-022"], status="covered"),
    CoverageEntry(paper_item_id="paper-028", covered_by=["unit-021"], status="covered"),
    CoverageEntry(paper_item_id="paper-029", covered_by=["unit-024"], status="covered"),
    CoverageEntry(
        paper_item_id="paper-030",
        covered_by=["unit-024"],
        status="covered",
        notes="论文没有独立局限章节；unit-024 必须把归纳内容标注为课程解释。",
    ),
]


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_DIR.mkdir(parents=True, exist_ok=True)

    paper_map = PaperMap(
        project_id="attention-is-all-you-need",
        source_ids=["source-001"],
        parser="manual-blueprint/1",
        generated_at=GENERATED_AT,
        elements=PAPER_ELEMENTS,
    )
    paper_path = write_json(FIXTURE_DIR / "paper_map.json", paper_map)
    digest = hashlib.sha256(paper_path.read_bytes()).hexdigest()

    coverage = CoverageMatrix(
        project_id="attention-is-all-you-need",
        paper_map_sha256=digest,
        entries=COVERAGE,
    )
    write_json(FIXTURE_DIR / "coverage_matrix.json", coverage)

    master = CourseMaster(
        project_id="attention-is-all-you-need",
        title="Attention Is All You Need：论文精读课程",
        language="zh-CN",
        audience="具备 Python 与基础深度学习背景的学习者",
        prerequisites=["Python", "基础深度学习", "序列模型（建议）"],
        chapters=CHAPTERS,
        units=UNITS,
        coverage=COVERAGE,
        source_ids=["source-001"],
        references=["source-001"],
        status="draft",
    )
    master_path = write_json(FIXTURE_DIR / "course_master.json", master)

    # Working copies for the project trial (git-ignored).
    for source in (
        FIXTURE_DIR / "paper_map.json",
        FIXTURE_DIR / "coverage_matrix.json",
    ):
        (PLAN_DIR / source.name).write_bytes(source.read_bytes())
    (PROJECT / "internal" / "course_master.json").write_bytes(master_path.read_bytes())

    total = sum(unit.estimated_minutes for unit in UNITS)
    print(f"paper elements: {len(PAPER_ELEMENTS)}")
    print(f"coverage entries: {len(COVERAGE)}")
    print(f"chapters: {len(CHAPTERS)}  units: {len(UNITS)}  planned minutes: {total}")
    print(f"paper_map sha256: {digest}")


if __name__ == "__main__":
    main()
