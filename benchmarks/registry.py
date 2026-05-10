from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import (
    adapt_gpqa_record,
    adapt_gsm8k_record,
    adapt_humaneval_record,
    adapt_longbench_v2_record,
    adapt_longmemeval_record,
    adapt_lveval_record,
    adapt_mmlu_record,
)
from .schemas import BenchmarkSample
from .smoke_samples import SMOKE_SAMPLES

try:
    from datasets import load_dataset
except Exception:  # pragma: no cover - optional dependency
    load_dataset = None

try:
    from huggingface_hub import hf_hub_download
except Exception:  # pragma: no cover - optional dependency
    hf_hub_download = None


LVEVAL_LENGTH_LEVELS = ("16k", "32k", "64k", "128k", "256k")
LVEVAL_TASK_FILES = {
    "dureader_mixup": "dureader_mixup.zip",
    "hotpotwikiqa_mixup": "hotpotwikiqa_mixup.zip",
    "multifieldqa_en_mixup": "multifieldqa_en_mixup.zip",
    "multifieldqa_zh_mixup": "multifieldqa_zh_mixup.zip",
    "lic_mixup": "lic_mixup.zip",
    "loogle_SD_mixup": "loogle_SD_mixup.zip",
    "loogle_CR_mixup": "loogle_CR_mixup.zip",
    "loogle_MIR_mixup": "loogle_MIR_mixup.zip",
    "factrecall_en": "factrecall_en.zip",
    "factrecall_zh": "factrecall_zh.zip",
    "cmrc_mixup": "cmrc_mixup.zip",
}


@dataclass(frozen=True)
class BenchmarkSpec:
    name: str
    source_kind: str
    loader: Callable[..., list[BenchmarkSample]]
    default_path: str | None = None
    default_config: str | None = None
    default_split: str | None = None


def _load_smoke_samples(name: str, sample_limit: int | None = None, **_: Any) -> list[BenchmarkSample]:
    samples = SMOKE_SAMPLES.get(name, [])
    return samples[:sample_limit] if sample_limit is not None else list(samples)


def _load_local_records(path: str) -> list[dict[str, Any]]:
    local_path = Path(path)
    if not local_path.exists():
        raise FileNotFoundError(f"本地 benchmark 文件不存在: {path}")

    suffix = local_path.suffix.lower()
    if suffix == ".json":
        content = json.loads(local_path.read_text(encoding="utf-8"))
        if isinstance(content, list):
            return [dict(item) for item in content]
        if isinstance(content, dict):
            for key in ("data", "records", "items", "examples"):
                if isinstance(content.get(key), list):
                    return [dict(item) for item in content[key]]
            return [content]
        raise ValueError(f"无法识别 JSON benchmark 格式: {path}")

    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        for line in local_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
        return records

    raise ValueError(f"暂不支持的本地 benchmark 文件格式: {path}")


def _parse_jsonl_text(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            records.append(json.loads(stripped))
    return records


def _load_jsonl_file(path: Path) -> list[dict[str, Any]]:
    return _parse_jsonl_text(path.read_text(encoding="utf-8"))


def _iter_lveval_config_names() -> list[str]:
    return [f"{task}_{length}" for task in LVEVAL_TASK_FILES for length in LVEVAL_LENGTH_LEVELS]


def _split_lveval_config(config: str) -> tuple[str, str]:
    for task_name in LVEVAL_TASK_FILES:
        prefix = f"{task_name}_"
        if config.startswith(prefix):
            return task_name, config[len(prefix) :]
    raise ValueError(
        "无效的 LV-Eval config。示例：factrecall_zh_256k、dureader_mixup_16k、hotpotwikiqa_mixup_32k"
    )


def _read_lveval_records_from_zip(zip_path: Path, config_name: str) -> list[dict[str, Any]]:
    task_name, _ = _split_lveval_config(config_name)
    candidate_paths = (
        f"{task_name}/{config_name}.jsonl",
        f"{config_name}.jsonl",
    )
    with zipfile.ZipFile(zip_path) as archive:
        for member in candidate_paths:
            if member in archive.namelist():
                with archive.open(member) as handle:
                    text = io.TextIOWrapper(handle, encoding="utf-8").read()
                return _parse_jsonl_text(text)
    raise FileNotFoundError(f"在压缩包中未找到 LV-Eval 配置文件: {config_name}.jsonl")


def _dedupe_lveval_records(records: list[dict[str, Any]], sample_limit: int | None = None) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for record in records:
        record_id = str(record.get("id") or record.get("sample_id") or record.get("custom_id") or "").strip()
        if record_id:
            if record_id in seen_ids:
                continue
            seen_ids.add(record_id)
        deduped.append(record)
        if sample_limit is not None and len(deduped) >= sample_limit:
            break
    return deduped


def _load_lveval_records(path: str | None, config: str | None, sample_limit: int | None) -> list[dict[str, Any]]:
    config_names = [config] if config else _iter_lveval_config_names()
    all_records: list[dict[str, Any]] = []

    if path:
        local_path = Path(path)
        if not local_path.exists():
            raise FileNotFoundError(f"LV-Eval 路径不存在: {path}")

        if local_path.is_dir():
            for config_name in config_names:
                task_name, _ = _split_lveval_config(config_name)
                candidates = [
                    local_path / task_name / f"{config_name}.jsonl",
                    local_path / f"{config_name}.jsonl",
                ]
                matched = next((candidate for candidate in candidates if candidate.exists()), None)
                if matched is None:
                    continue
                all_records.extend(_load_jsonl_file(matched))
                all_records = _dedupe_lveval_records(all_records, sample_limit=sample_limit)
                if sample_limit is not None and len(all_records) >= sample_limit:
                    return all_records
            if all_records:
                return all_records
            raise FileNotFoundError(f"目录中未找到匹配的 LV-Eval JSONL: {path}")

        suffix = local_path.suffix.lower()
        if suffix == ".zip":
            if not config:
                raise ValueError("读取本地 LV-Eval zip 时必须提供 --config，例如 factrecall_zh_256k")
            records = _dedupe_lveval_records(_read_lveval_records_from_zip(local_path, config), sample_limit=sample_limit)
            return records
        if suffix == ".jsonl":
            records = _dedupe_lveval_records(_load_jsonl_file(local_path), sample_limit=sample_limit)
            return records
        raise ValueError(f"不支持的 LV-Eval 本地文件格式: {path}")

    if hf_hub_download is None:
        raise RuntimeError("缺少 huggingface_hub 依赖，无法自动下载 LV-Eval 数据")

    for config_name in config_names:
        task_name, _ = _split_lveval_config(config_name)
        archive_path = hf_hub_download(
            repo_id="Infinigence/LVEval",
            repo_type="dataset",
            filename=LVEVAL_TASK_FILES[task_name],
        )
        all_records.extend(_read_lveval_records_from_zip(Path(archive_path), config_name))
        all_records = _dedupe_lveval_records(all_records, sample_limit=sample_limit)
        if sample_limit is not None and len(all_records) >= sample_limit:
            return all_records
    return all_records


def _load_with_adapter(
    name: str,
    adapter: Callable[[dict[str, Any], str], BenchmarkSample],
    path: str | None,
    hf_path: str,
    config: str | None,
    split: str | None,
    sample_limit: int | None,
) -> list[BenchmarkSample]:
    if path and Path(path).exists():
        records = _load_local_records(path)
        if sample_limit is not None:
            records = records[:sample_limit]
        return [adapter(record, name) for record in records]
    return _load_hf_samples(
        name=name,
        path=hf_path,
        config=config,
        split=split,
        sample_limit=sample_limit,
        adapter=adapter,
    )


def _load_hf_samples(
    name: str,
    path: str,
    adapter: Callable[[dict[str, Any], str], BenchmarkSample],
    config: str | None = None,
    split: str | None = None,
    sample_limit: int | None = None,
) -> list[BenchmarkSample]:
    if load_dataset is None:
        raise RuntimeError("缺少 datasets 依赖，请先安装：pip install datasets")

    effective_split = split or "test"
    dataset = load_dataset(path, config, split=effective_split)
    if sample_limit is not None:
        dataset = dataset.select(range(min(sample_limit, len(dataset))))
    return [adapter(dict(item), name) for item in dataset]


def _load_longmemeval(name: str, path: str | None = None, config: str | None = None, split: str | None = None, sample_limit: int | None = None) -> list[BenchmarkSample]:
    return _load_with_adapter(
        name=name,
        adapter=adapt_longmemeval_record,
        path=path,
        hf_path="kellyhongg/cleaned-longmemeval-s",
        config=config,
        split=split or "train",
        sample_limit=sample_limit,
    )


def _load_lveval(name: str, path: str | None = None, config: str | None = None, split: str | None = None, sample_limit: int | None = None) -> list[BenchmarkSample]:
    del split  # LV-Eval 当前走自定义 zip/jsonl 加载，不区分 HF split
    records = _load_lveval_records(path=path, config=config, sample_limit=None)
    samples: list[BenchmarkSample] = []
    seen_ids: set[str] = set()
    for record in records:
        sample = adapt_lveval_record(record, name)
        if sample.id in seen_ids:
            continue
        seen_ids.add(sample.id)
        samples.append(sample)
        if sample_limit is not None and len(samples) >= sample_limit:
            break
    return samples


def _load_longbench_v2(name: str, path: str | None = None, config: str | None = None, split: str | None = None, sample_limit: int | None = None) -> list[BenchmarkSample]:
    del split
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    if hf_hub_download is not None:
        try:
            local = hf_hub_download(repo_id="THUDM/LongBench-v2", filename="data.json", repo_type="dataset")
            candidates.append(Path(local))
        except Exception:
            pass
    data: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            break
    if not data:
        raise RuntimeError("LongBench-v2 data.json not found; pass `path=` or ensure huggingface_hub access")
    samples: list[BenchmarkSample] = []
    length_filter = (config or "").strip().lower() or None
    for record in data:
        if length_filter and length_filter not in {"all", "any"}:
            rec_length = str(record.get("length", "")).strip().lower()
            if rec_length != length_filter:
                continue
        sample = adapt_longbench_v2_record(record, name)
        samples.append(sample)
        if sample_limit is not None and len(samples) >= sample_limit:
            break
    return samples


def _load_mmlu(name: str, path: str | None = None, config: str | None = None, split: str | None = None, sample_limit: int | None = None) -> list[BenchmarkSample]:
    return _load_with_adapter(
        name=name,
        adapter=adapt_mmlu_record,
        path=path,
        hf_path="lukaemon/mmlu",
        config=config or "abstract_algebra",
        split=split or "test",
        sample_limit=sample_limit,
    )


def _load_gpqa(name: str, path: str | None = None, config: str | None = None, split: str | None = None, sample_limit: int | None = None) -> list[BenchmarkSample]:
    return _load_with_adapter(
        name=name,
        adapter=adapt_gpqa_record,
        path=path,
        hf_path="lukaemon/gpqa",
        config=config or "gpqa_diamond",
        split=split or "train",
        sample_limit=sample_limit,
    )


def _load_gsm8k(name: str, path: str | None = None, config: str | None = None, split: str | None = None, sample_limit: int | None = None) -> list[BenchmarkSample]:
    return _load_with_adapter(
        name=name,
        adapter=adapt_gsm8k_record,
        path=path,
        hf_path="openai/gsm8k",
        config=config or "main",
        split=split or "test",
        sample_limit=sample_limit,
    )


def _load_humaneval(name: str, path: str | None = None, config: str | None = None, split: str | None = None, sample_limit: int | None = None) -> list[BenchmarkSample]:
    return _load_with_adapter(
        name=name,
        adapter=adapt_humaneval_record,
        path=path,
        hf_path="openai/humaneval",
        config=config,
        split=split or "test",
        sample_limit=sample_limit,
    )


BENCHMARK_SPECS = {
    "longmemeval_smoke": BenchmarkSpec(name="longmemeval_smoke", source_kind="smoke", loader=_load_smoke_samples),
    "generalization_smoke": BenchmarkSpec(name="generalization_smoke", source_kind="smoke", loader=_load_smoke_samples),
    "lveval_smoke": BenchmarkSpec(name="lveval_smoke", source_kind="smoke", loader=_load_smoke_samples),
    "mmlu_smoke": BenchmarkSpec(name="mmlu_smoke", source_kind="smoke", loader=_load_smoke_samples),
    "gsm8k_smoke": BenchmarkSpec(name="gsm8k_smoke", source_kind="smoke", loader=_load_smoke_samples),
    "humaneval_smoke": BenchmarkSpec(name="humaneval_smoke", source_kind="smoke", loader=_load_smoke_samples),
    "longmemeval_s": BenchmarkSpec(name="longmemeval_s", source_kind="huggingface", loader=_load_longmemeval),
    "lveval": BenchmarkSpec(name="lveval", source_kind="huggingface", loader=_load_lveval),
    "longbench_v2": BenchmarkSpec(name="longbench_v2", source_kind="huggingface", loader=_load_longbench_v2),
    "mmlu": BenchmarkSpec(name="mmlu", source_kind="huggingface", loader=_load_mmlu),
    "gpqa_diamond": BenchmarkSpec(name="gpqa_diamond", source_kind="huggingface", loader=_load_gpqa),
    "gsm8k": BenchmarkSpec(name="gsm8k", source_kind="huggingface", loader=_load_gsm8k),
    "humaneval": BenchmarkSpec(name="humaneval", source_kind="huggingface", loader=_load_humaneval),
}


def list_benchmarks() -> list[str]:
    return sorted(BENCHMARK_SPECS.keys())


def load_benchmark_samples(
    name: str,
    sample_limit: int | None = None,
    path: str | None = None,
    config: str | None = None,
    split: str | None = None,
) -> list[BenchmarkSample]:
    if name not in BENCHMARK_SPECS:
        raise KeyError(f"未知 benchmark: {name}")
    spec = BENCHMARK_SPECS[name]
    return spec.loader(name=name, sample_limit=sample_limit, path=path, config=config, split=split)
