from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

from mase import MASESystem
from model_interface import load_config, load_memory_settings, resolve_config_path

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "memory_runs" / "hotswap-validation"
TEMP_CONFIG_PATH = WORKSPACE_DIR / "config.hotswap.json"


def write_config(config: dict) -> None:
    TEMP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMP_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    base_config = load_config(resolve_config_path())
    test_config = deepcopy(base_config)

    memory_dir = (WORKSPACE_DIR / "memory").resolve()
    if memory_dir.exists():
        shutil.rmtree(memory_dir)

    test_config["memory"]["json_dir"] = str(memory_dir)
    test_config["memory"]["index_db"] = str((memory_dir / "index.db").resolve())
    test_config["models"]["router"]["model_name"] = "qwen2.5:3b"
    test_config["models"]["executor"]["model_name"] = "qwen2.5:3b"
    write_config(test_config)

    system = MASESystem(TEMP_CONFIG_PATH)
    initial_models = system.describe_models()
    initial_trace = system.run_with_trace("请记住：热插拔测试端口是7788。", log=False)

    reloaded_config = deepcopy(test_config)
    reloaded_config["models"]["router"]["model_name"] = "qwen2.5:0.5b"
    reloaded_config["models"]["executor"]["model_name"] = "qwen2.5:7b"
    write_config(reloaded_config)

    system.reload()
    reloaded_models = system.describe_models()
    route_after_reload = system.call_router("服务器端口是多少？")
    math_answer = system.call_executor(
        user_question="计算 (7 + 1) * 8 等于多少？",
        fact_sheet="",
        allow_general_knowledge=True,
        task_type="math_compute",
        use_memory=False,
    )
    memory_settings = load_memory_settings(TEMP_CONFIG_PATH)

    report = {
        "config_path": str(TEMP_CONFIG_PATH),
        "memory_dir": str(memory_settings["json_dir"]),
        "initial_models": initial_models,
        "reloaded_models": reloaded_models,
        "record_path": initial_trace.record_path,
        "route_after_reload": route_after_reload,
        "math_answer": math_answer,
        "record_path_in_configured_memory": initial_trace.record_path.startswith(str(memory_settings["json_dir"])),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def test_load_memory_settings_uses_mase_runs_dir_for_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "memory": {
                    "json_dir": "memory",
                    "log_dir": "logs",
                    "index_db": "memory/index.db",
                }
            }
        ),
        encoding="utf-8",
    )
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("MASE_RUNS_DIR", str(runs_dir))

    settings = load_memory_settings(config_path)

    assert settings["json_dir"] == (runs_dir / "memory").resolve()
    assert settings["log_dir"] == (runs_dir / "memory" / "logs").resolve()
    assert settings["index_db"] == (runs_dir / "memory" / "index.db").resolve()


def test_memory_root_uses_mase_runs_dir(tmp_path, monkeypatch):
    from mase.utils import memory_root

    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_RUNS_DIR", str(tmp_path / "runs"))

    assert memory_root() == (tmp_path / "runs" / "memory").resolve()


if __name__ == "__main__":
    main()
