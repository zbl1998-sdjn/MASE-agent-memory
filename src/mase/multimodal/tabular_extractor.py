"""CSV/Excel 确定性表格抽取器(零 LLM,全可复现)。

表格是天生结构化数据,不需要模型转写——与 kv_extract/structure_facts
同族的第三类确定性抽取,直接在解析层产出候选事实:

- 两列表 = KV 形态:每行一条 fact(key=第一列,value=第二列);
- ≥3 列表 = 行打包:key=首格,value=该行完整渲染切片(structure_facts
  表格行打包同族:首格作键,其余原文作值);
- full_text 为逐 sheet 的确定性渲染,值逐字出现其中 → 治理层 evidence
  机械 span 定位天然通过;
- 空表/全空行零产出(halluc_ok 模式);每 sheet 事实数上限护栏,超出
  只截断产出并记 warning(不静默,全文仍完整保留供 FTS 检索);
- CSV 编码探测 utf-8-sig → gbk(中文导出件双主流),结果如实记入
  metadata;openpyxl 为可选依赖,缺失抛 MissingDependencyError 带安装
  指引(与 PyMuPDF 同模式)。
"""
from __future__ import annotations

import csv
import io
from typing import Any

from .document_loader import MediaPayload, MissingDependencyError, TabularSource
from .extractor import CandidateFact, ExtractionResult, MediaAssetInfo

_CELL_SEP = " | "
_KEY_MAX_CHARS = 60
_MAX_FACTS_PER_SHEET = 200
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _render_cell(value: Any) -> str:
    """单元格 → 确定性文本;int 不得渲染成 42.0,None 渲染为空串。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _decode_csv(data: bytes) -> tuple[str, str]:
    """utf-8-sig 优先、gbk 回退;返回 (文本, 实际编码)。都失败原样抛。"""
    try:
        return data.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        return data.decode("gbk"), "gbk"


def _load_csv_sheets(source: TabularSource) -> tuple[list[tuple[str, list[list[str]]]], str]:
    text, encoding = _decode_csv(source.path.read_bytes())
    sample = text[:4096]
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # 单列/空文件等嗅探不出时回退逗号
    rows = [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), dialect)]
    return [(source.path.stem, rows)], encoding


def _load_xlsx_sheets(source: TabularSource) -> list[tuple[str, list[list[str]]]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise MissingDependencyError(
            "解析 .xlsx 需要 openpyxl。请安装: pip install \"mase-memory[multimodal]\" "
            "或 pip install \"openpyxl>=3.1,<4.0\""
        ) from exc

    sheets: list[tuple[str, list[list[str]]]] = []
    # data_only=True:公式取最近一次计算值;read_only 控制大文件内存。
    workbook = openpyxl.load_workbook(source.path, read_only=True, data_only=True)
    try:
        for worksheet in workbook.worksheets:
            rows = [[_render_cell(cell) for cell in row] for row in worksheet.iter_rows(values_only=True)]
            sheets.append((str(worksheet.title), rows))
    finally:
        workbook.close()
    return sheets


def _row_facts(rows: list[list[str]], rendered_lines: list[str]) -> list[CandidateFact]:
    """按 KV/行打包契约产出事实;rendered_lines 与 rows 一一对应。"""
    nonempty = [(row, line) for row, line in zip(rows, rendered_lines, strict=True)
                if any(cell for cell in row)]
    facts: list[CandidateFact] = []
    for row, line in nonempty:
        cells = [c for c in row if c]
        if len(cells) < 2:
            continue  # 孤立单格没有键值结构,留在 full_text 里供检索即可
        key = cells[0]
        if len(key) > _KEY_MAX_CHARS:
            continue
        value = cells[1] if len(cells) == 2 else _CELL_SEP.join(cells[1:])
        facts.append(CandidateFact(
            category="general_facts",
            key=key,
            value=value,
            confidence=0.7,  # 规则抽取尽力值;值逐字来自渲染原文
            evidence=line,
        ))
    return facts


class TabularExtractor:
    """CSV/XLSX → 确定性 full_text + 候选事实。"""

    name = "tabular"
    version = "1"
    model_name = "deterministic-parser"

    def supports(self, media_type: str) -> bool:
        return media_type in ("text/csv", _XLSX_MIME)

    def extract(self, asset: MediaAssetInfo, payload: MediaPayload) -> ExtractionResult:
        source = payload.tabular
        if source is None:
            raise ValueError("TabularExtractor requires a tabular payload")

        metadata: dict[str, Any] = {"parser": "csv" if source.media_type == "text/csv" else "openpyxl"}
        if source.media_type == "text/csv":
            sheets, encoding = _load_csv_sheets(source)
            metadata["encoding"] = encoding
        else:
            sheets = _load_xlsx_sheets(source)

        text_blocks: list[str] = []
        facts: list[CandidateFact] = []
        warnings: list[str] = []
        for sheet_name, rows in sheets:
            rendered_lines = [_CELL_SEP.join(row).strip() for row in rows]
            block_lines = [line for line in rendered_lines if line]
            if block_lines:
                text_blocks.append(f"[Sheet] {sheet_name}\n" + "\n".join(block_lines))
            sheet_facts = _row_facts(rows, rendered_lines)
            if len(sheet_facts) > _MAX_FACTS_PER_SHEET:
                warnings.append(
                    f"sheet {sheet_name!r}: {len(sheet_facts)} 行事实超过上限 "
                    f"{_MAX_FACTS_PER_SHEET},仅保留前 {_MAX_FACTS_PER_SHEET} 条"
                    "(全文完整保留,可经检索命中)"
                )
                sheet_facts = sheet_facts[:_MAX_FACTS_PER_SHEET]
            facts.extend(sheet_facts)

        return ExtractionResult(
            full_text="\n\n".join(text_blocks),
            candidate_facts=tuple(facts),
            extractor_name=self.name,
            model_name=self.model_name,
            extractor_version=self.version,
            warnings=tuple(warnings),
            metadata=metadata,
        )


__all__ = ["TabularExtractor"]
