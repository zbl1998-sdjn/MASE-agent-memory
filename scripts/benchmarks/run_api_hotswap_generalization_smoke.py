from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import PROJECT_ROOT
    from .run_api_hotswap_longmem_smoke import (
        configure_cloud_reliability as configure_longmem_cloud_reliability,
    )
    from .run_api_hotswap_longmem_smoke import (
        configure_executor as configure_longmem_executor,
    )
    from .run_api_hotswap_longmem_smoke import (
        configure_notetaker as configure_longmem_notetaker,
    )
    from .run_api_hotswap_longmem_smoke import (
        configure_planner as configure_longmem_planner,
    )
    from .run_api_hotswap_longmem_smoke import (
        configure_router as configure_longmem_router,
    )
    from .run_nolima_mase_smoke import _run_suite
except ImportError:
    from _bootstrap import PROJECT_ROOT
    from run_api_hotswap_longmem_smoke import (
        configure_cloud_reliability as configure_longmem_cloud_reliability,
    )
    from run_api_hotswap_longmem_smoke import (
        configure_executor as configure_longmem_executor,
    )
    from run_api_hotswap_longmem_smoke import (
        configure_notetaker as configure_longmem_notetaker,
    )
    from run_api_hotswap_longmem_smoke import (
        configure_planner as configure_longmem_planner,
    )
    from run_api_hotswap_longmem_smoke import (
        configure_router as configure_longmem_router,
    )
    from run_nolima_mase_smoke import _run_suite

from model_interface import load_config, resolve_config_path

BASE_DIR = PROJECT_ROOT
WORKSPACE_DIR = BASE_DIR / "memory_runs" / "api-hotswap-generalization-smoke"
TEMP_CONFIG_PATH = WORKSPACE_DIR / "config.runtime.json"
TEMP_ENV_PATH = WORKSPACE_DIR / ".env.runtime"
RESULT_PATH = BASE_DIR / "results" / "generalization-regression" / "cloud-hotswap-generalization-smoke.json"
_PROJECT_ENV_LOADED = False


def load_project_env() -> None:
    global _PROJECT_ENV_LOADED
    if _PROJECT_ENV_LOADED:
        return
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip()
    _PROJECT_ENV_LOADED = True


def require_env(name: str) -> str:
    load_project_env()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value


def write_env_file(values: dict[str, str]) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_ENV_PATH.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")


def configure_cloud_subset(config: dict[str, Any]) -> None:
    configure_longmem_router(config)
    configure_longmem_notetaker(config)
    configure_longmem_planner(config)
    configure_longmem_executor(config)
    configure_longmem_cloud_reliability(config)


def build_runtime_config() -> dict[str, Any]:
    base_config = load_config(resolve_config_path())
    runtime_config = deepcopy(base_config)
    memory_dir = (WORKSPACE_DIR / "memory").resolve()
    if memory_dir.exists():
        shutil.rmtree(memory_dir)
    runtime_config["memory"]["json_dir"] = str(memory_dir)
    runtime_config["memory"]["index_db"] = str((memory_dir / "index.db").resolve())
    runtime_config["env_file"] = str(TEMP_ENV_PATH.resolve())
    configure_cloud_subset(runtime_config)
    return runtime_config


def write_runtime_config(config: dict[str, Any]) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def run_command(command: list[str], extra_env: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=BASE_DIR,
        env={**os.environ, **extra_env},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def read_bamboo_detail(path: Path) -> dict[str, Any]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not rows:
        return {}
    row = rows[0]
    return {
        "prediction": row.get("prediction"),
        "answer": row.get("dataset_answer"),
        "error": row.get("error"),
    }


def main() -> None:
    env_values = {
        "QWEN35_PLUS_API_KEY": require_env("QWEN35_PLUS_API_KEY"),
        "DEEPSEEK_API_KEY": require_env("DEEPSEEK_API_KEY"),
        "MINIMAX_API_KEY": require_env("MINIMAX_API_KEY"),
        "KIMI_K25_API_KEY": require_env("KIMI_K25_API_KEY"),
        "GLM51_API_KEY": require_env("GLM51_API_KEY"),
    }
    write_env_file(env_values)
    runtime_config = build_runtime_config()
    write_runtime_config(runtime_config)
    extra_env = {
        "MASE_CONFIG_PATH": str(TEMP_CONFIG_PATH.resolve()),
        "MASE_ENABLE_MODEL_AUTONOMY": "1",
    }

    bamboo_root = BASE_DIR / "external-benchmarks" / "BAMBOO" / "outputs" / "cloud-hotswap"
    if bamboo_root.exists():
        shutil.rmtree(bamboo_root)
    bamboo_root.mkdir(parents=True, exist_ok=True)

    meetingqa_run = bamboo_root / "meetingqa_1"
    meetingpred_run = bamboo_root / "meetingpred_3"

    meetingqa_result = run_command(
        [
            "python",
            ".\\external-benchmarks\\BAMBOO\\run_mase_official.py",
            "--dataset",
            "external-benchmarks\\BAMBOO\\datasets\\meetingqa_4k.jsonl",
            "--limit",
            "1",
            "--run-dir",
            str(meetingqa_run.relative_to(BASE_DIR)),
        ],
        extra_env,
    )
    meetingpred_result = run_command(
        [
            "python",
            ".\\external-benchmarks\\BAMBOO\\run_mase_official.py",
            "--dataset",
            "external-benchmarks\\BAMBOO\\datasets\\meetingpred_4k.jsonl",
            "--limit",
            "3",
            "--run-dir",
            str(meetingpred_run.relative_to(BASE_DIR)),
        ],
        extra_env,
    )

    previous_config = os.environ.get("MASE_CONFIG_PATH")
    previous_autonomy = os.environ.get("MASE_ENABLE_MODEL_AUTONOMY")
    os.environ["MASE_CONFIG_PATH"] = str(TEMP_CONFIG_PATH.resolve())
    os.environ["MASE_ENABLE_MODEL_AUTONOMY"] = "1"
    try:
        nolima_smoke = _run_suite(
            suite_name="cloud_smoke_direct_1k_subset",
            needle_set_path=BASE_DIR / "external-benchmarks" / "NoLiMa" / "data" / "needlesets" / "needle_set_ONLYDirect.json",
            question_types={"direct"},
            context_length=1000,
            haystack_files=["rand_book_1.txt"],
            max_cases=2,
            depth_percent=50.0,
        )
        nolima_onehop_smoke = _run_suite(
            suite_name="cloud_smoke_onehop_2k_subset",
            needle_set_path=BASE_DIR / "external-benchmarks" / "NoLiMa" / "data" / "needlesets" / "needle_set.json",
            question_types={"onehop"},
            context_length=2000,
            haystack_files=["rand_book_1.txt"],
            max_cases=4,
            depth_percent=50.0,
        )
    finally:
        if previous_config is None:
            os.environ.pop("MASE_CONFIG_PATH", None)
        else:
            os.environ["MASE_CONFIG_PATH"] = previous_config
        if previous_autonomy is None:
            os.environ.pop("MASE_ENABLE_MODEL_AUTONOMY", None)
        else:
            os.environ["MASE_ENABLE_MODEL_AUTONOMY"] = previous_autonomy

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_config_path": str(TEMP_CONFIG_PATH),
        "autonomy_lane_enabled": True,
        "cloud_subset": {
            "router": runtime_config["models"]["router"].get("model_name"),
            "notetaker_hot": runtime_config["models"]["notetaker"].get("modes", {}).get("hot_ops", {}).get("model_name"),
            "notetaker_cold": runtime_config["models"]["notetaker"].get("modes", {}).get("cold_ops", {}).get("model_name"),
            "notetaker_default": runtime_config["models"]["notetaker"].get("model_name"),
            "planner": runtime_config["models"]["planner"].get("model_name"),
            "executor_general": runtime_config["models"]["executor"].get("model_name"),
            "executor_reasoning": runtime_config["models"]["executor"].get("modes", {}).get(
                "grounded_answer_english_reasoning", {}
            ).get("model_name"),
        },
        "bamboo": {
            "meetingqa_1": {
                "command": meetingqa_result,
                "detail": read_bamboo_detail(meetingqa_run / "meetingqa.details.json") if (meetingqa_run / "meetingqa.details.json").exists() else {},
            },
            "meetingpred_3": {
                "command": meetingpred_result,
                "detail": json.loads((meetingpred_run / "meetingpred.details.json").read_text(encoding="utf-8"))
                if (meetingpred_run / "meetingpred.details.json").exists()
                else [],
            },
        },
        "nolima": {
            "direct_subset_accuracy": nolima_smoke.get("accuracy"),
            "direct_subset_pass_count": nolima_smoke.get("pass_count"),
            "direct_subset_sample_count": nolima_smoke.get("sample_count"),
            "direct_rows": nolima_smoke.get("rows"),
            "onehop_subset_accuracy": nolima_onehop_smoke.get("accuracy"),
            "onehop_subset_pass_count": nolima_onehop_smoke.get("pass_count"),
            "onehop_subset_sample_count": nolima_onehop_smoke.get("sample_count"),
            "onehop_rows": nolima_onehop_smoke.get("rows"),
        },
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
