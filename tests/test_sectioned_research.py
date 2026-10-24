from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio.errors import ProviderError
from content_studio.models import (
    EvidenceLedger,
    EvidenceRecord,
    PaperElement,
    PaperMap,
    ProjectConfig,
    SourceRecord,
    SourceRegistry,
    TableEvidence,
)
from content_studio.paths import ensure_project_layout
from content_studio.providers.base import (
    GenerationRequest,
    GenerationResult,
    ModelProvider,
    Usage,
)
from content_studio.research import (
    load_evidence_ledger,
    run_research,
    write_evidence_csv,
)
from content_studio.source_map import chunk_text, load_source_map
from content_studio.utils import write_json, write_text


def _paragraph(label: str) -> str:
    return "".join(
        f"{label} 第{index}句用于测试分节研究，内容不构成真实结论。" for index in range(1, 80)
    )


def _quote_from_prompt(request: GenerationRequest) -> tuple[str, str]:
    chunk_id = ""
    for line in request.messages[-1].content.splitlines():
        if line.startswith("### "):
            chunk_id = line[4:].split(" | ", 1)[0]
        elif chunk_id and len(line.strip()) >= 40:
            return chunk_id, line.strip()[:120]
    return "", ""


class RecordingProvider(ModelProvider):
    name = "recording"
    model = "recording-1"

    def __init__(self, *, repeat_statement: bool = False) -> None:
        self.requests: list[GenerationRequest] = []
        self.calls = 0
        self.repeat_statement = repeat_statement

    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise AssertionError("generate_structured is the only entry point under test")

    def generate_structured(self, request, schema):
        self.calls += 1
        self.requests.append(request)
        statement = (
            "The same claim is reported twice."
            if self.repeat_statement
            else f"Claim number {self.calls} is measurable."
        )
        chunk_id, excerpt = _quote_from_prompt(request)
        payload = {
            "section": f"Mock section {self.calls}",
            "summary": "Fixture summary.",
            "claims": [
                {
                    "claim_id": "claim-001",
                    "statement": statement,
                    "claim_type": "fact",
                    "importance": "key",
                }
            ],
            "evidence": [
                {
                    "evidence_id": "evidence-001",
                    "source_id": "source-001",
                    "chunk_id": chunk_id,
                    "claim_id": "claim-001",
                    "evidence_type": "quote",
                    "locator": chunk_id,
                    "source_excerpt": excerpt,
                    "support_relation": "supports",
                    "verification_status": "unverified",
                }
            ],
            "paper_elements": [
                {
                    "kind": "result",
                    "title": f"Result {self.calls}",
                    "locator": f"p.{self.calls}",
                    "notes": "",
                }
            ],
            "unknowns": [f"Unknown {self.calls}"],
            "limitations": ["Only a fixture."],
            "source_conflicts": [],
        }
        self.last_result = GenerationResult(
            text="structured fixture",
            provider=self.name,
            model=self.model,
            usage=Usage(input_tokens=11, output_tokens=3),
            finish_reason="stop",
            request_id=f"req-{self.calls}",
        )
        return schema.model_validate(payload)


class NonVerbatimProvider(RecordingProvider):
    def generate_structured(self, request, schema):
        result = super().generate_structured(request, schema)
        result.evidence = [
            record.model_copy(
                update={"source_excerpt": "This sentence is not in the source at all."}
            )
            for record in result.evidence
        ]
        return result


class ChunkLocatorProvider(RecordingProvider):
    def generate_structured(self, request, schema):
        result = super().generate_structured(request, schema)
        first = request.metadata["chunk_ids"].split(",")[0]
        result.evidence = [
            record.model_copy(update={"locator": first}) for record in result.evidence
        ]
        return result


class FailingProvider(RecordingProvider):
    def generate_structured(self, request, schema):
        if self.calls >= 1:
            raise ProviderError("simulated window failure", provider=self.name)
        return super().generate_structured(request, schema)


def _project(tmp_path: Path) -> tuple[Path, ProjectConfig, str]:
    root = ensure_project_layout(tmp_path / "project")
    text = (
        "# Paper\n\n"
        "1\nIntroduction\n\n"
        + _paragraph("引言")
        + "\n\n2\nMethod\n\n"
        + _paragraph("方法")
        + "\n\n3\nResults\n\n"
        + _paragraph("结果")
        + "\n"
    )
    (root / "internal" / "sources").mkdir(parents=True, exist_ok=True)
    write_text(root / "internal" / "sources" / "source-001.txt", text)

    registry = SourceRegistry(
        project_id="demo",
        sources=[
            SourceRecord(
                source_id="source-001",
                title="Paper",
                kind="markdown",
                origin="input/paper.md",
            )
        ],
    )
    write_json(root / "internal" / "source_registry.json", registry)
    config = ProjectConfig(project_id="demo", title="Demo paper")
    return root, config, text


def test_every_chunk_is_sent_whole_and_nothing_is_truncated(tmp_path: Path):
    root, config, text = _project(tmp_path)
    provider = RecordingProvider()

    run_research(root, config, provider, prompt_char_budget=2500)

    source_map = load_source_map(root)
    assert source_map is not None
    document = source_map.documents[0]
    assert len(document.chunks) > 1
    assert len(provider.requests) > 1

    prompts = [request.messages[-1].content for request in provider.requests]
    for chunk in document.chunks:
        body = chunk_text(text, chunk)
        matches = [prompt for prompt in prompts if body in prompt]
        assert len(matches) == 1, f"{chunk.chunk_id} was not sent exactly once"

    assert not any("[truncated]" in prompt for prompt in prompts)
    assert all("区块头由系统添加" in prompt for prompt in prompts)


def test_ids_are_renumbered_evidence_remapped_and_calls_traced(tmp_path: Path):
    root, config, _ = _project(tmp_path)
    provider = RecordingProvider()

    brief, ledger = run_research(root, config, provider, prompt_char_budget=2500)
    calls = provider.calls

    claims = json.loads((root / "internal" / "claims.json").read_text(encoding="utf-8"))
    claim_ids = [claim["claim_id"] for claim in claims]
    assert claim_ids == [f"claim-{index:03d}" for index in range(1, calls + 1)]
    assert all(claim["verification_status"] == "pending" for claim in claims)

    evidence_ids = [record.evidence_id for record in ledger.records]
    assert evidence_ids == [f"evidence-{index:03d}" for index in range(1, calls + 1)]
    assert {record.claim_id for record in ledger.records} == set(claim_ids)
    assert all(record.verification_status == "unverified" for record in ledger.records)
    assert len(brief.findings) == calls

    analysis = json.loads(
        (root / "internal" / "research_analysis.json").read_text(encoding="utf-8")
    )
    trace = analysis["research_calls"]
    assert len(trace) == calls
    assert all(item["finish_reason"] == "stop" for item in trace)
    assert analysis["quote_audit"]["verified_exact"] == calls
    assert analysis["quote_audit"]["needs_review"] == 0
    assert [item["request_id"] for item in trace] == [
        f"req-{index}" for index in range(1, calls + 1)
    ]
    assert analysis["usage"]["input_tokens"] == 11 * calls
    assert analysis["usage"]["output_tokens"] == 3 * calls

    extracted = json.loads(
        (root / "internal" / "plan" / "paper_map.extracted.json").read_text(encoding="utf-8")
    )
    assert len(extracted["elements"]) == calls
    assert (root / "internal" / "plan" / "paper_map.json").is_file()


class StructuredProvider(ModelProvider):
    name = "structured"
    model = "structured-1"

    def __init__(self, scope: str = "row") -> None:
        self.calls = 0
        self.scope = scope

    def generate(self, request):  # pragma: no cover - structured only
        raise AssertionError("generate_structured is the only entry point under test")

    def generate_structured(self, request, schema):
        self.calls += 1
        payload = {
            "section": "6 Results",
            "summary": "Fixture table.",
            "claims": [
                {
                    "claim_id": "claim-001",
                    "statement": "The base model reaches 27.3 BLEU on EN-DE.",
                    "claim_type": "fact",
                    "importance": "key",
                }
            ],
            "evidence": [
                {
                    "evidence_id": "evidence-001",
                    "source_id": "source-001",
                    "chunk_id": "source-001:b0000",
                    "claim_id": "claim-001",
                    "evidence_type": "table",
                    "locator": "§6 Results",
                    "support_relation": "supports",
                    "table": TableEvidence(
                        scope=self.scope,
                        table_id="Table 2",
                        row_label="Transformer (base model)",
                        column_label="EN-DE",
                        value="27.3",
                        variant="base",
                        locator="§6 Results",
                    ).model_dump(),
                }
            ],
            "paper_elements": [],
            "unknowns": [],
            "limitations": [],
            "source_conflicts": [],
        }
        self.last_result = GenerationResult(
            text="structured fixture",
            provider=self.name,
            model=self.model,
            usage=Usage(input_tokens=3, output_tokens=2),
            finish_reason="stop",
        )
        return schema.model_validate(payload)


def _structured_project(tmp_path: Path) -> tuple[Path, ProjectConfig]:
    root = ensure_project_layout(tmp_path / "structured")
    text = (
        "6"
        + chr(10)
        + "Results"
        + chr(10) * 2
        + "Table 2: BLEU results."
        + chr(10) * 2
        + "Transformer (base model) 27.3 38.1 EN-DE"
        + chr(10)
    )
    write_text(root / "internal" / "sources" / "source-001.txt", text)
    registry = SourceRegistry(
        project_id="demo",
        sources=[
            SourceRecord(
                source_id="source-001",
                title="Paper",
                kind="markdown",
                origin="input/paper.md",
            )
        ],
    )
    write_json(root / "internal" / "source_registry.json", registry)
    paper_map = PaperMap(
        project_id="demo",
        elements=[
            PaperElement(
                paper_item_id="paper-001",
                kind="table",
                title="Table 2: BLEU results",
                locator="§6 Results Table 2",
            )
        ],
    )
    write_json(root / "internal" / "plan" / "paper_map.json", paper_map)
    return root, ProjectConfig(project_id="demo", title="Structured")


def test_table_evidence_row_is_reviewed_without_column_semantics(tmp_path: Path):
    root, config = _structured_project(tmp_path)

    _, ledger = run_research(root, config, StructuredProvider(), prompt_char_budget=100000)

    # Row/value co-occurrence is no longer enough: the column mapping is not
    # programmatically proven, so the table stays out of the formal ledger.
    assert ledger.records == []
    payload = json.loads((root / "internal" / "research_analysis.json").read_text(encoding="utf-8"))
    assert payload["structured_audit"]["verified_structured"] == 0
    assert payload["structured_audit"]["needs_review"] == 1
    audit = json.loads(
        (root / "internal" / "qa" / "structured_evidence_audit.json").read_text(encoding="utf-8")
    )
    review = audit["reviews"][0]
    assert review["reason"] == "column_semantics_unverified"
    assert review["source_id"] == "source-001"
    assert review["scope"] == "row"
    assert review["verification_method"] == "row_span"


def test_prose_scope_is_not_table_evidence(tmp_path: Path):
    root, config = _structured_project(tmp_path)

    _, ledger = run_research(
        root,
        config,
        StructuredProvider(scope="prose"),
        prompt_char_budget=100000,
    )

    assert ledger.records == []
    audit = json.loads(
        (root / "internal" / "qa" / "structured_evidence_audit.json").read_text(encoding="utf-8")
    )
    review = audit["reviews"][0]
    assert review["reason"] == "prose_not_table_cell"
    assert review["scope"] == "prose"


def test_structured_evidence_survives_csv_roundtrip(tmp_path: Path):
    record = EvidenceRecord(
        evidence_id="evidence-001",
        source_id="source-001",
        chunk_id="source-001:b0000",
        claim_id="claim-001",
        evidence_type="table",
        support_relation="supports",
        quote_status="verified_structured",
        table=TableEvidence(
            scope="cell",
            table_id="paper-001",
            row_label="Transformer (base model)",
            column_label="EN-DE",
            value="27.3",
            variant="base",
            locator="§6.1",
        ),
    )
    write_evidence_csv(
        tmp_path / "internal" / "evidence_ledger.csv",
        EvidenceLedger(project_id="demo", records=[record]),
    )
    loaded = load_evidence_ledger(tmp_path)
    assert len(loaded.records) == 1
    assert loaded.records[0].table is not None
    assert loaded.records[0].table.value == "27.3"
    assert loaded.records[0].quote_status == "verified_structured"
    assert loaded.records[0].table.scope == "cell"


def test_failed_window_keeps_a_checkpoint(tmp_path: Path):
    root, config, _ = _project(tmp_path)

    with pytest.raises(ProviderError):
        run_research(root, config, FailingProvider(), prompt_char_budget=2500)

    checkpoint = json.loads(
        (root / "internal" / "research_checkpoint.json").read_text(encoding="utf-8")
    )
    assert len(checkpoint["calls"]) == 1
    assert len(checkpoint["claims"]) == 1
    assert checkpoint["calls"][0]["finish_reason"] == "stop"


def test_chunk_id_locators_are_mapped_to_sections(tmp_path: Path):
    root, config, _ = _project(tmp_path)

    _, ledger = run_research(root, config, ChunkLocatorProvider(), prompt_char_budget=100000)

    assert ledger.records
    assert all(record.locator.startswith("§") for record in ledger.records)


def test_bibliography_chunks_are_excluded_and_not_sent(tmp_path: Path):
    root, config, text = _project(tmp_path)
    source_path = root / "internal" / "sources" / "source-001.txt"
    extra = (
        chr(10)
        + "References"
        + chr(10)
        + "[1] A bibliography entry."
        + chr(10)
        + "[2] Another entry."
        + chr(10)
    )
    write_text(source_path, text + extra)

    provider = RecordingProvider()
    run_research(root, config, provider, prompt_char_budget=100000)

    payload = json.loads((root / "internal" / "research_analysis.json").read_text(encoding="utf-8"))
    excluded = payload["excluded_chunks"]
    assert excluded
    assert {item["section"] for item in excluded} == {"References"}
    sent = {chunk_id for call in payload["research_calls"] for chunk_id in call["chunk_ids"]}
    assert sent.isdisjoint({item["chunk_id"] for item in excluded})


def test_windows_stay_focused_on_a_few_sections(tmp_path: Path):
    root, config, text = _project(tmp_path)
    source_path = root / "internal" / "sources" / "source-001.txt"
    extra = "".join(
        chr(10)
        + str(index)
        + chr(10)
        + f"Section {index}"
        + chr(10)
        + (f"Content for section {index}. " * 120)
        + chr(10)
        for index in range(4, 9)
    )
    write_text(source_path, text + extra)

    provider = RecordingProvider()
    run_research(root, config, provider, prompt_char_budget=8000)

    from content_studio.source_map import load_source_map

    source_map = load_source_map(root)
    assert source_map is not None
    chunk_section = {
        chunk.chunk_id: chunk.section
        for document in source_map.documents
        for chunk in document.chunks
    }
    payload = json.loads((root / "internal" / "research_analysis.json").read_text(encoding="utf-8"))
    for call in payload["research_calls"]:
        sections = {
            chunk_section[chunk_id] for chunk_id in call["chunk_ids"] if chunk_section.get(chunk_id)
        }
        assert len(sections) <= 4
    assert len(payload["research_calls"]) > 1


def test_unlocatable_candidates_are_not_formal_evidence(tmp_path: Path):
    root, config, _ = _project(tmp_path)
    provider = NonVerbatimProvider()

    _, ledger = run_research(root, config, provider, prompt_char_budget=2500)

    assert ledger.records == []
    payload = json.loads((root / "internal" / "research_analysis.json").read_text(encoding="utf-8"))
    assert payload["quote_audit"]["needs_review"] == provider.calls
    assert payload["non_verbatim_evidence"] == provider.calls
    audit = json.loads((root / "internal" / "qa" / "quote_audit.json").read_text(encoding="utf-8"))
    assert len(audit["reviews"]) == provider.calls
    assert all(item["reason"] in {"not_found", "not_found_in_section"} for item in audit["reviews"])


def test_repeated_claims_are_deduplicated_but_their_evidence_is_kept(tmp_path: Path):
    root, config, _ = _project(tmp_path)
    provider = RecordingProvider(repeat_statement=True)

    _, ledger = run_research(root, config, provider, prompt_char_budget=2500)
    claims = json.loads((root / "internal" / "claims.json").read_text(encoding="utf-8"))

    assert len(claims) == 1
    assert len(ledger.records) == provider.calls
    assert {record.claim_id for record in ledger.records} == {"claim-001"}

    analysis = json.loads(
        (root / "internal" / "research_analysis.json").read_text(encoding="utf-8")
    )
    assert analysis["merged_claims"] == provider.calls - 1


def test_a_human_paper_map_is_not_overwritten(tmp_path: Path):
    root, config, _ = _project(tmp_path)
    plan_dir = root / "internal" / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    sentinel = PaperMap(
        project_id="demo",
        elements=[
            PaperElement(
                paper_item_id="paper-001",
                kind="section",
                title="Human blueprint",
                locator="Abstract",
            )
        ],
    )
    path = write_json(plan_dir / "paper_map.json", sentinel)
    before = path.read_bytes()

    run_research(root, config, RecordingProvider(), prompt_char_budget=2500)

    assert path.read_bytes() == before
    assert (plan_dir / "paper_map.extracted.json").is_file()
