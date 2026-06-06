"""模型调用成本中心：加载价格目录并汇总 trace 中的用量与估算成本。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc

ROOT = Path(__file__).resolve().parents[2]
LOCAL_PROVIDERS = {"ollama", "llama_cpp", "llamacpp", "llama.cpp", "local", "localhost"}
FALSEY = {"0", "false", "no", "n", "off", "disabled"}


def _as_float(value: Any) -> float | None:
    """宽松转换为 float；bool/空值视为缺失。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    """按顺序返回第一个存在且非 None 的字段。"""
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _as_int(value: Any) -> int:
    """宽松转换为非负整数，用于 token/call 计数。"""
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _is_enabled(value: Any) -> bool:
    """解析 catalog enabled 字段；缺省视为启用。"""
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in FALSEY


def _is_local_provider(provider: str | None) -> bool:
    """判断 provider 是否属于本地/免费模型通道。"""
    return str(provider or "").strip().lower() in LOCAL_PROVIDERS


def _normalize_model_key(provider: str | None, model_name: str | None) -> str:
    """统一 by_model 分桶键。"""
    return f"{str(provider or 'unknown').strip()}:{str(model_name or 'unknown').strip()}"


def _resolve_relative_path(raw_path: str | Path, base_dir: Path) -> Path:
    """解析相对配置路径；相对路径以配置文件所在目录为基准。"""
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _pricing_path_from_config(config_path: str | Path | None) -> tuple[Path | None, str | None]:
    """从 config.json 的 pricing.catalog 字段解析价格目录路径。"""
    if config_path is None:
        return None, None
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        return None, None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    pricing = config.get("pricing") if isinstance(config, dict) else None
    if not isinstance(pricing, dict):
        return None, None
    raw_catalog = pricing.get("catalog") or pricing.get("catalog_path")
    if not raw_catalog:
        return None, None
    return _resolve_relative_path(raw_catalog, path.parent), "config.pricing.catalog"


def resolve_pricing_catalog_path(config_path: str | Path | None = None) -> tuple[Path, str]:
    """按 env -> config -> 默认文件的优先级定位价格目录。"""
    env_path = os.environ.get("MASE_PRICING_CATALOG_PATH")
    if env_path and env_path.strip():
        return Path(env_path).expanduser().resolve(), "env.MASE_PRICING_CATALOG_PATH"
    config_catalog_path, source = _pricing_path_from_config(config_path)
    if config_catalog_path is not None and source is not None:
        return config_catalog_path, source
    return (ROOT / "pricing.json").resolve(), "default.ROOT/pricing.json"


def _raw_items(payload: Any) -> list[dict[str, Any]]:
    """兼容多种价格目录顶层字段名，返回原始 item 列表。"""
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "catalog", "prices", "models"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _raw_budget_rules(payload: Any) -> list[dict[str, Any]]:
    """读取可选预算规则，当前只做透传。"""
    if not isinstance(payload, dict):
        return []
    value = payload.get("budget_rules")
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [dict(value)]
    return []


def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """把目录 item 归一成成本中心内部字段。"""
    provider = str(item.get("provider") or "").strip()
    model_name = str(item.get("model_name") or item.get("model") or "").strip()
    if not provider or not model_name:
        return None
    flat_cost = _as_float(item.get("cost_per_1k_tokens"))
    input_cost = _as_float(_first_present(item, "input_cost_per_1k_tokens", "prompt_cost_per_1k_tokens"))
    output_cost = _as_float(_first_present(item, "output_cost_per_1k_tokens", "completion_cost_per_1k_tokens"))
    return {
        "provider": provider,
        "model_name": model_name,
        "input_cost_per_1k_tokens": input_cost,
        "output_cost_per_1k_tokens": output_cost,
        "cost_per_1k_tokens": flat_cost,
        "currency": str(item.get("currency") or "USD").strip() or "USD",
        "source": item.get("source"),
        "effective_from": item.get("effective_from"),
        "enabled": _is_enabled(item.get("enabled")),
    }


def load_pricing_catalog(config_path: str | Path | None = None) -> dict[str, Any]:
    """加载价格目录，并把失败状态编码进 metadata 而不是抛出异常。"""
    path, source = resolve_pricing_catalog_path(config_path)
    metadata: dict[str, Any] = {
        "path": str(path),
        "source": source,
        "exists": path.exists(),
        "missing_file": not path.exists(),
        "file_missing": not path.exists(),
        "loaded": False,
        "item_count": 0,
        "warning_count": 0,
        "warnings": [],
    }
    if not path.exists():
        return {"items": [], "catalog": [], "budget_rules": [], "metadata": metadata}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        metadata["warnings"].append(f"pricing_catalog_load_failed:{type(error).__name__}")
        metadata["warning_count"] = len(metadata["warnings"])
        return {"items": [], "catalog": [], "budget_rules": [], "metadata": metadata}

    items = [item for item in (_normalize_item(raw) for raw in _raw_items(payload)) if item is not None]
    metadata["loaded"] = True
    metadata["item_count"] = len(items)
    return {"items": items, "catalog": items, "budget_rules": _raw_budget_rules(payload), "metadata": metadata}


def _catalog_items(catalog: Any) -> list[dict[str, Any]]:
    """从已加载 catalog 结构中取可匹配条目。"""
    if isinstance(catalog, dict):
        items = catalog.get("items") or catalog.get("catalog") or catalog.get("prices") or []
        return [dict(item) for item in items if isinstance(item, dict)]
    if isinstance(catalog, list):
        return [dict(item) for item in catalog if isinstance(item, dict)]
    return []


def _match_catalog_item(provider: str, model_name: str, catalog: Any) -> dict[str, Any] | None:
    """按 provider/model 精确或通配匹配价格目录项。"""
    provider_key = provider.strip().lower()
    model_key = model_name.strip().lower()
    for item in _catalog_items(catalog):
        if not _is_enabled(item.get("enabled")):
            continue
        item_provider = str(item.get("provider") or "").strip().lower()
        item_model = str(item.get("model_name") or item.get("model") or "").strip().lower()
        provider_matches = item_provider in {provider_key, "*"}
        model_matches = item_model in {model_key, "*"}
        if provider_matches and model_matches:
            return item
    return None


def resolve_price(provider: str | None, model_name: str | None, catalog: Any) -> dict[str, Any]:
    """解析单个 provider/model 的价格状态。"""
    provider_text = str(provider or "").strip()
    model_text = str(model_name or "").strip()
    if _is_local_provider(provider_text):
        # 本地 provider 固定为 priced/free，避免本地调用污染未定价告警。
        return {
            "status": "priced",
            "pricing_status": "priced",
            "pricing_type": "local",
            "reason": "local_provider_free",
            "provider": provider_text,
            "model_name": model_text,
            "priced": True,
            "is_local": True,
            "is_free": True,
            "currency": "USD",
            "input_cost_per_1k_tokens": 0.0,
            "output_cost_per_1k_tokens": 0.0,
            "cost_per_1k_tokens": 0.0,
            "source": "local_provider",
        }

    item = _match_catalog_item(provider_text, model_text, catalog)
    if item is None:
        # 云模型缺失价格时保持 warn-only，不阻断 trace 展示。
        return {
            "status": "unpriced",
            "pricing_status": "unpriced",
            "pricing_type": "missing",
            "reason": "catalog_miss",
            "provider": provider_text,
            "model_name": model_text,
            "priced": False,
            "is_local": False,
            "is_free": False,
            "currency": None,
            "input_cost_per_1k_tokens": None,
            "output_cost_per_1k_tokens": None,
            "cost_per_1k_tokens": None,
            "source": None,
        }

    flat_cost = _as_float(item.get("cost_per_1k_tokens"))
    input_cost = _as_float(_first_present(item, "input_cost_per_1k_tokens", "prompt_cost_per_1k_tokens"))
    output_cost = _as_float(_first_present(item, "output_cost_per_1k_tokens", "completion_cost_per_1k_tokens"))
    if flat_cost is not None:
        input_cost = flat_cost if input_cost is None else input_cost
        output_cost = flat_cost if output_cost is None else output_cost
    if input_cost is None or output_cost is None:
        # 部分价格项不可用于精确估算，标记 partial 方便补齐目录。
        return {
            "status": "unpriced",
            "pricing_status": "unpriced",
            "pricing_type": "partial",
            "reason": "partial_catalog_item",
            "provider": provider_text,
            "model_name": model_text,
            "priced": False,
            "is_local": False,
            "is_free": False,
            "currency": item.get("currency"),
            "input_cost_per_1k_tokens": input_cost,
            "output_cost_per_1k_tokens": output_cost,
            "cost_per_1k_tokens": flat_cost,
            "source": item.get("source"),
        }
    return {
        "status": "priced",
        "pricing_status": "priced",
        "pricing_type": "catalog",
        "reason": "catalog_match",
        "provider": provider_text,
        "model_name": model_text,
        "priced": True,
        "is_local": False,
        "is_free": input_cost == 0.0 and output_cost == 0.0,
        "currency": item.get("currency") or "USD",
        "input_cost_per_1k_tokens": input_cost,
        "output_cost_per_1k_tokens": output_cost,
        "cost_per_1k_tokens": flat_cost,
        "source": item.get("source"),
    }


def _estimate_call_cost(call: dict[str, Any], price: dict[str, Any]) -> float | None:
    """按输入/输出 token 单价估算一次调用成本。"""
    if not price.get("priced"):
        return None
    prompt_tokens = _as_int(call.get("prompt_tokens"))
    completion_tokens = _as_int(call.get("completion_tokens"))
    input_cost = float(price.get("input_cost_per_1k_tokens") or 0.0)
    output_cost = float(price.get("output_cost_per_1k_tokens") or 0.0)
    cost = (prompt_tokens / 1000.0 * input_cost) + (completion_tokens / 1000.0 * output_cost)
    return round(cost, 8)


def _new_bucket(name: str) -> dict[str, Any]:
    """创建 agent/model/totals 聚合桶。"""
    return {
        "name": name,
        "call_count": 0,
        "priced_call_count": 0,
        "unpriced_call_count": 0,
        "local_free_call_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "ledger_estimated_cost_usd": 0.0,
    }


def _add_to_bucket(bucket: dict[str, Any], call: dict[str, Any], price: dict[str, Any], call_cost: float | None) -> None:
    """把一次模型调用累加到聚合桶。"""
    bucket["call_count"] += 1
    bucket["prompt_tokens"] += _as_int(call.get("prompt_tokens"))
    bucket["completion_tokens"] += _as_int(call.get("completion_tokens"))
    bucket["total_tokens"] += _as_int(call.get("total_tokens"))
    bucket["ledger_estimated_cost_usd"] += _as_float(call.get("estimated_cost_usd")) or 0.0
    if price.get("priced"):
        bucket["priced_call_count"] += 1
    else:
        bucket["unpriced_call_count"] += 1
    if price.get("is_local") and price.get("is_free"):
        bucket["local_free_call_count"] += 1
    if call_cost is not None:
        bucket["estimated_cost_usd"] += call_cost


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    """输出前统一四舍五入成本字段。"""
    return {
        **bucket,
        "estimated_cost_usd": round(float(bucket["estimated_cost_usd"]), 8),
        "ledger_estimated_cost_usd": round(float(bucket["ledger_estimated_cost_usd"]), 8),
    }


def _safe_recent_event(call: dict[str, Any], price: dict[str, Any], call_cost: float | None) -> dict[str, Any]:
    """裁剪最近调用事件，避免把完整 prompt/response 泄漏到成本面板。"""
    keys = {
        "call_id",
        "created_at",
        "agent_role",
        "agent_type",
        "mode",
        "provider",
        "model_name",
        "is_local",
        "success",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "token_source",
        "fallback_from",
        "fallback_to",
    }
    event = {key: value for key, value in call.items() if key in keys}
    event.update(
        {
            "pricing_status": price.get("pricing_status"),
            "pricing_type": price.get("pricing_type"),
            "pricing_reason": price.get("reason"),
            "priced": bool(price.get("priced")),
            "currency": price.get("currency"),
            "estimated_cost_usd": call_cost,
            "ledger_estimated_cost_usd": call.get("estimated_cost_usd"),
            "pricing_source": price.get("source"),
        }
    )
    return event


def build_cost_center(model_calls: list[dict[str, Any]], catalog: Any, recent_limit: int = 50) -> dict[str, Any]:
    """汇总模型调用，生成前端成本中心消费的稳定 JSON 结构。"""
    limit = _as_int(recent_limit) or 50
    by_agent: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    unpriced_models: dict[str, dict[str, Any]] = {}
    totals = _new_bucket("totals")
    totals.update({"local_call_count": 0, "cloud_call_count": 0})
    recent_events: list[dict[str, Any]] = []

    for call in model_calls:
        # 逐条重新按 catalog 估价，便于发现 ledger 内估算和当前目录的差异。
        provider = str(call.get("provider") or "")
        model_name = str(call.get("model_name") or "")
        price = resolve_price(provider, model_name, catalog)
        call_cost = _estimate_call_cost(call, price)
        _add_to_bucket(totals, call, price, call_cost)
        if price.get("is_local"):
            totals["local_call_count"] += 1
        else:
            totals["cloud_call_count"] += 1

        agent_key = str(call.get("agent_role") or call.get("agent_type") or "unknown")
        model_key = _normalize_model_key(provider, model_name)
        _add_to_bucket(by_agent.setdefault(agent_key, _new_bucket(agent_key)), call, price, call_cost)
        _add_to_bucket(by_model.setdefault(model_key, _new_bucket(model_key)), call, price, call_cost)
        if not price.get("priced") and not price.get("is_local"):
            # 未定价云模型单独聚合，推动补齐 pricing.json。
            model_row = unpriced_models.setdefault(
                model_key,
                {
                    "provider": provider or "unknown",
                    "model_name": model_name or "unknown",
                    "call_count": 0,
                    "total_tokens": 0,
                },
            )
            model_row["call_count"] += 1
            model_row["total_tokens"] += _as_int(call.get("total_tokens"))
        recent_events.append(_safe_recent_event(call, price, call_cost))

    finalized_totals = _finalize_bucket(totals)
    total_calls = int(finalized_totals["call_count"])
    priced_calls = int(finalized_totals["priced_call_count"])
    warning_count = int(finalized_totals["unpriced_call_count"])
    # 无调用时覆盖率为 1.0，避免空面板被误判为价格缺口。
    coverage_ratio = round(priced_calls / total_calls, 6) if total_calls else 1.0
    pricing_coverage = {
        "catalog_item_count": len(_catalog_items(catalog)),
        "total_call_count": total_calls,
        "priced_call_count": priced_calls,
        "unpriced_call_count": warning_count,
        "local_free_call_count": int(finalized_totals["local_free_call_count"]),
        "cloud_call_count": int(finalized_totals["cloud_call_count"]),
        "coverage_ratio": coverage_ratio,
        "unpriced_models": sorted(unpriced_models.values(), key=lambda row: (row["provider"], row["model_name"])),
        "policy": "warn_only",
    }
    return {
        "schema_version": "mase.cost_center.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "totals": finalized_totals,
        "by_agent": [_finalize_bucket(row) for _, row in sorted(by_agent.items())],
        "by_model": [_finalize_bucket(row) for _, row in sorted(by_model.items())],
        "recent_events": recent_events[-limit:],
        "pricing_coverage": pricing_coverage,
        "unpriced_call_count": warning_count,
        "warning_count": warning_count,
    }
