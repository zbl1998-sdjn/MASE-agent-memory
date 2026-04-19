from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy

try:
    from ._bootstrap import PROJECT_ROOT
except ImportError:
    from _bootstrap import PROJECT_ROOT
from mase import MASESystem
from model_interface import load_config, resolve_config_path

BASE_DIR = PROJECT_ROOT
WORKSPACE_DIR = BASE_DIR / "memory_runs" / "api-hotswap-longmem-smoke"
TEMP_CONFIG_PATH = WORKSPACE_DIR / "config.runtime.json"
TEMP_ENV_PATH = WORKSPACE_DIR / ".env.runtime"
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
    lines = [f"{key}={value}" for key, value in values.items()]
    TEMP_ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def qwen_candidate(model_name: str) -> dict:
    return {
        "provider": "anthropic",
        "base_url": "https://coding.dashscope.aliyuncs.com/apps/anthropic",
        "api_key_env": "QWEN35_PLUS_API_KEY",
        "auth_header": "x-api-key",
        "auth_scheme": "",
        "model_name": model_name,
    }


def deepseek_candidate(model_name: str) -> dict:
    return {
        "provider": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key_env": "DEEPSEEK_API_KEY",
        "auth_header": "x-api-key",
        "auth_scheme": "",
        "model_name": model_name,
    }


def minimax_candidate(model_name: str) -> dict:
    return {
        "provider": "anthropic",
        "base_url": "https://api.minimaxi.com/anthropic",
        "api_key_env": "MINIMAX_API_KEY",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "model_name": model_name,
    }


def kimi_candidate(model_name: str) -> dict:
    return {
        "provider": "anthropic",
        "base_url": "https://api.kimi.com/coding/",
        "api_key_env": "KIMI_K25_API_KEY",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "model_name": model_name,
    }


def glm_candidate(model_name: str) -> dict:
    return {
        "provider": "anthropic",
        "base_url": "https://open.bigmodel.cn/api/anthropic",
        "api_key_env": "GLM51_API_KEY",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "model_name": model_name,
    }


def set_cloud_resilience(
    agent_config: dict,
    *,
    overall_timeout: float | None = None,
    connect_timeout: float,
    read_timeout: float,
    write_timeout: float = 20,
    pool_timeout: float = 10,
    retry_count: int = 2,
    retry_base_delay: float = 0.8,
    retry_max_delay: float = 4.0,
    retry_jitter: float = 0.35,
    fallback_models: list[dict] | None = None,
) -> None:
    if overall_timeout is not None:
        agent_config["timeout_seconds"] = overall_timeout
    agent_config["connect_timeout_seconds"] = connect_timeout
    agent_config["read_timeout_seconds"] = read_timeout
    agent_config["write_timeout_seconds"] = write_timeout
    agent_config["pool_timeout_seconds"] = pool_timeout
    agent_config["retry_count"] = retry_count
    agent_config["retry_base_delay"] = retry_base_delay
    agent_config["retry_max_delay"] = retry_max_delay
    agent_config["retry_jitter"] = retry_jitter
    if fallback_models:
        agent_config["fallback_models"] = fallback_models


def configure_cloud_reliability(config: dict) -> None:
    fallbacks = config.setdefault("fallbacks", {})
    fallbacks.update(
        {
            "cloud_timeout_seconds": 60,
            "cloud_connect_timeout_seconds": 8,
            "cloud_read_timeout_seconds": 45,
            "cloud_write_timeout_seconds": 20,
            "cloud_pool_timeout_seconds": 10,
            "cloud_max_connections": 24,
            "cloud_max_keepalive_connections": 12,
            "cloud_keepalive_expiry_seconds": 30,
            "cloud_retry_count": 2,
            "cloud_retry_base_delay": 0.8,
            "cloud_retry_max_delay": 4.0,
            "cloud_retry_jitter": 0.35,
            "cloud_retry_backoff_multiplier": 2.0,
        }
    )

    router = config["models"]["router"]
    set_cloud_resilience(
        router,
        overall_timeout=22,
        connect_timeout=5,
        read_timeout=18,
        write_timeout=10,
        pool_timeout=6,
        fallback_models=[
            deepseek_candidate("deepseek-chat"),
            minimax_candidate("MiniMax-M2.5"),
            glm_candidate("glm-5-turbo"),
        ],
    )

    notetaker = config["models"]["notetaker"]
    set_cloud_resilience(
        notetaker,
        overall_timeout=32,
        connect_timeout=6,
        read_timeout=28,
        fallback_models=[
            deepseek_candidate("deepseek-reasoner"),
            minimax_candidate("MiniMax-M2.5"),
            glm_candidate("glm-5-turbo"),
        ],
    )
    modes = notetaker.setdefault("modes", {})
    for mode_name in ("cold_ops", "english_ops", "english_aux_ops"):
        if mode_name in modes:
            set_cloud_resilience(
                modes[mode_name],
                overall_timeout=32,
                connect_timeout=6,
                read_timeout=28,
                fallback_models=[
                    deepseek_candidate("deepseek-reasoner"),
                    minimax_candidate("MiniMax-M2.5"),
                    glm_candidate("glm-5-turbo"),
                ],
            )
    for mode_name in ("cold_summary",):
        if mode_name in modes:
            set_cloud_resilience(
                modes[mode_name],
                overall_timeout=22,
                connect_timeout=6,
                read_timeout=18,
                fallback_models=[
                    minimax_candidate("MiniMax-M2.5"),
                    deepseek_candidate("deepseek-reasoner"),
                ],
            )
    for mode_name in ("hot_ops", "hot_summary", "english_summary"):
        if mode_name in modes:
            set_cloud_resilience(
                modes[mode_name],
                overall_timeout=26,
                connect_timeout=6,
                read_timeout=22,
                fallback_models=[
                    minimax_candidate("MiniMax-M2.7"),
                    minimax_candidate("MiniMax-M2.5-highspeed"),
                    minimax_candidate("MiniMax-M2.5"),
                    deepseek_candidate("deepseek-chat"),
                ],
            )

    planner = config["models"]["planner"]
    set_cloud_resilience(
        planner,
        overall_timeout=50,
        connect_timeout=8,
        read_timeout=45,
        fallback_models=[
            glm_candidate("glm-5-turbo"),
            deepseek_candidate("deepseek-reasoner"),
            deepseek_candidate("deepseek-chat"),
        ],
    )
    planner_modes = planner.setdefault("modes", {})
    for mode_name in ("task_planning", "retrieval_verification", "session_summary"):
        if mode_name in planner_modes:
            set_cloud_resilience(
                planner_modes[mode_name],
                overall_timeout=50 if mode_name in {"task_planning", "retrieval_verification"} else 32,
                connect_timeout=8,
                read_timeout=45 if mode_name in {"task_planning", "retrieval_verification"} else 28,
                fallback_models=[
                    glm_candidate("glm-5-turbo"),
                    deepseek_candidate("deepseek-reasoner"),
                    deepseek_candidate("deepseek-chat"),
                ],
            )

    executor = config["models"]["executor"]
    set_cloud_resilience(
        executor,
        overall_timeout=60,
        connect_timeout=8,
        read_timeout=55,
        fallback_models=[
            kimi_candidate("kimi-k2"),
            glm_candidate("glm-5.1"),
            deepseek_candidate("deepseek-chat"),
        ],
    )
    executor_modes = executor.setdefault("modes", {})
    for mode_name in (
        "grounded_answer",
        "grounded_answer_general",
        "general_answer",
        "general_answer_general",
        "structured_task",
        "structured_task_general",
        "code_generation",
        "code_generation_general",
    ):
        if mode_name in executor_modes:
            set_cloud_resilience(
                executor_modes[mode_name],
                overall_timeout=45,
                connect_timeout=8,
                read_timeout=40,
                fallback_models=[
                    kimi_candidate("kimi-k2"),
                    kimi_candidate("kimi-k2-turbo-preview"),
                    glm_candidate("glm-5.1"),
                    deepseek_candidate("deepseek-chat"),
                ],
            )
    for mode_name in (
        "grounded_analysis",
        "grounded_disambiguation",
        "grounded_verify_reasoning",
        "grounded_answer_reasoning",
        "grounded_analysis_reasoning",
        "grounded_disambiguation_reasoning",
        "grounded_verify_english_reasoning",
        "grounded_answer_english_reasoning",
        "grounded_analysis_english_reasoning",
        "grounded_disambiguation_english_reasoning",
        "general_answer_reasoning",
        "code_generation_reasoning",
        "math_compute",
        "math_compute_general",
        "math_compute_reasoning",
        "structured_task_reasoning",
    ):
        if mode_name in executor_modes:
            set_cloud_resilience(
                executor_modes[mode_name],
                overall_timeout=60,
                connect_timeout=8,
                read_timeout=55,
                fallback_models=[
                    glm_candidate("glm-5-turbo"),
                    deepseek_candidate("deepseek-reasoner"),
                    deepseek_candidate("deepseek-chat"),
                ],
            )


def configure_router(config: dict) -> None:
    router = config["models"]["router"]
    router.update(
        {
            "provider": "anthropic",
            "base_url": "https://coding.dashscope.aliyuncs.com/apps/anthropic",
            "api_key_env": "QWEN35_PLUS_API_KEY",
            "auth_header": "x-api-key",
            "auth_scheme": "",
            "model_name": "qwen3.5-plus",
            "max_tokens": 128,
            "temperature": 0.0,
        }
    )


def configure_notetaker(config: dict) -> None:
    notetaker = config["models"]["notetaker"]
    notetaker.update(
        {
            "provider": "anthropic",
            "base_url": "https://api.deepseek.com/anthropic",
            "api_key_env": "DEEPSEEK_API_KEY",
            "auth_header": "x-api-key",
            "auth_scheme": "",
            "model_name": "deepseek-chat",
            "max_tokens": 256,
            "temperature": 0.1,
        }
    )
    modes = notetaker.setdefault("modes", {})
    modes["hot_ops"] = {
        **modes.get("hot_ops", {}),
        "provider": "anthropic",
        "base_url": "https://api.minimaxi.com/anthropic",
        "api_key_env": "MINIMAX_API_KEY",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "model_name": "MiniMax-M2.7-highspeed",
        "temperature": 0.0,
        "max_tokens": 192,
    }
    modes["hot_summary"] = {
        **modes.get("hot_summary", {}),
        "provider": "anthropic",
        "base_url": "https://api.minimaxi.com/anthropic",
        "api_key_env": "MINIMAX_API_KEY",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "model_name": "MiniMax-M2.7-highspeed",
        "temperature": 0.0,
        "max_tokens": 96,
    }
    modes["cold_ops"] = {
        **modes.get("cold_ops", {}),
        "provider": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key_env": "DEEPSEEK_API_KEY",
        "auth_header": "x-api-key",
        "auth_scheme": "",
        "model_name": "deepseek-chat",
        "temperature": 0.1,
        "max_tokens": 256,
    }
    modes["cold_summary"] = {
        **modes.get("cold_summary", {}),
        "provider": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key_env": "DEEPSEEK_API_KEY",
        "auth_header": "x-api-key",
        "auth_scheme": "",
        "model_name": "deepseek-chat",
        "temperature": 0.0,
        "max_tokens": 128,
    }
    modes["english_ops"] = {
        **modes.get("english_ops", {}),
        "provider": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key_env": "DEEPSEEK_API_KEY",
        "auth_header": "x-api-key",
        "auth_scheme": "",
        "model_name": "deepseek-chat",
        "temperature": 0.0,
        "max_tokens": 224,
    }
    modes["english_aux_ops"] = {
        **modes.get("english_aux_ops", {}),
        "provider": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key_env": "DEEPSEEK_API_KEY",
        "auth_header": "x-api-key",
        "auth_scheme": "",
        "model_name": "deepseek-chat",
        "temperature": 0.0,
        "max_tokens": 192,
    }
    modes["english_summary"] = {
        **modes.get("english_summary", {}),
        "provider": "anthropic",
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key_env": "DEEPSEEK_API_KEY",
        "auth_header": "x-api-key",
        "auth_scheme": "",
        "model_name": "deepseek-chat",
        "temperature": 0.0,
        "max_tokens": 128,
    }


def configure_planner(config: dict) -> None:
    planner = config["models"]["planner"]
    planner.update(
        {
            "provider": "anthropic",
            "base_url": "https://open.bigmodel.cn/api/anthropic",
            "api_key_env": "GLM51_API_KEY",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer",
            "model_name": "glm-5.1",
            "max_tokens": 384,
            "temperature": 0.0,
        }
    )
    modes = planner.setdefault("modes", {})
    modes["task_planning"] = {
        **modes.get("task_planning", {}),
        "provider": "anthropic",
        "base_url": "https://open.bigmodel.cn/api/anthropic",
        "api_key_env": "GLM51_API_KEY",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "model_name": "glm-5.1",
        "temperature": 0.0,
        "max_tokens": 384,
    }
    modes["retrieval_verification"] = {
        **modes.get("retrieval_verification", {}),
        "provider": "anthropic",
        "base_url": "https://open.bigmodel.cn/api/anthropic",
        "api_key_env": "GLM51_API_KEY",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "model_name": "glm-5.1",
        "temperature": 0.0,
        "max_tokens": 384,
    }
    modes["session_summary"] = {
        **modes.get("session_summary", {}),
        "provider": "anthropic",
        "base_url": "https://open.bigmodel.cn/api/anthropic",
        "api_key_env": "GLM51_API_KEY",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        "model_name": "glm-5.1",
        "temperature": 0.0,
        "max_tokens": 192,
    }


def configure_executor(config: dict) -> None:
    executor = config["models"]["executor"]
    executor.update(
        {
            "provider": "anthropic",
            "base_url": "https://api.kimi.com/coding/",
            "api_key_env": "KIMI_K25_API_KEY",
            "auth_header": "Authorization",
            "auth_scheme": "Bearer",
            "model_name": "kimi-k2.5",
            "max_tokens": 1024,
            "temperature": 0.2,
        }
    )
    modes = executor.setdefault("modes", {})
    kimi_targets = [
        "grounded_answer",
        "grounded_answer_general",
        "general_answer",
        "general_answer_general",
        "structured_task",
        "structured_task_general",
        "code_generation",
        "code_generation_general",
    ]
    glm_targets = [
        "grounded_analysis",
        "grounded_disambiguation",
        "grounded_verify_reasoning",
        "grounded_answer_reasoning",
        "grounded_analysis_reasoning",
        "grounded_disambiguation_reasoning",
        "grounded_verify_english_reasoning",
        "grounded_answer_english_reasoning",
        "grounded_analysis_english_reasoning",
        "grounded_disambiguation_english_reasoning",
        "general_answer_reasoning",
        "code_generation_reasoning",
        "math_compute",
        "math_compute_general",
        "math_compute_reasoning",
        "structured_task_reasoning",
    ]
    for key in kimi_targets:
        if key in modes:
            modes[key] = {
                **modes[key],
                "provider": "anthropic",
                "base_url": "https://api.kimi.com/coding/",
                "api_key_env": "KIMI_K25_API_KEY",
                "auth_header": "Authorization",
                "auth_scheme": "Bearer",
                "model_name": "kimi-k2.5",
            }
    for key in glm_targets:
        if key in modes:
            modes[key] = {
                **modes[key],
                "provider": "anthropic",
                "base_url": "https://open.bigmodel.cn/api/anthropic",
                "api_key_env": "GLM51_API_KEY",
                "auth_header": "Authorization",
                "auth_scheme": "Bearer",
                "model_name": "glm-5.1",
            }


def tighten_runtime_prompts(config: dict) -> None:
    executor = config["models"]["executor"]
    executor["system_prompt"] = (
        "You are the execution agent inside MASE.\n"
        "- Prefer concise final answers.\n"
        "- Do not add extra background unless the user explicitly asks.\n"
        "- When a task is memory-grounded, stay strictly within the evidence package."
    )
    modes = executor.setdefault("modes", {})
    if "general_answer" in modes:
        modes["general_answer"]["system_prompt"] = (
            "You are MASE's general executor.\n"
            "- Reply concisely.\n"
            "- Do not introduce speculative details.\n"
            "- Do not ask follow-up questions unless explicitly requested."
        )
    if "grounded_answer" in modes:
        modes["grounded_answer"]["system_prompt"] = (
            "You are MASE's grounded executor.\n"
            "- Answer only from the fact sheet.\n"
            "- Give the shortest exact answer that fully satisfies the question.\n"
            "- Do not add adjacent facts unless explicitly requested.\n"
            "- If evidence is insufficient, return the refusal sentence."
        )


def build_runtime_config() -> dict:
    base_config = load_config(resolve_config_path())
    runtime_config = deepcopy(base_config)
    memory_dir = (WORKSPACE_DIR / "memory").resolve()
    if memory_dir.exists():
        shutil.rmtree(memory_dir)
    runtime_config["memory"]["json_dir"] = str(memory_dir)
    runtime_config["memory"]["index_db"] = str((memory_dir / "index.db").resolve())
    runtime_config["env_file"] = str(TEMP_ENV_PATH.resolve())
    configure_router(runtime_config)
    configure_notetaker(runtime_config)
    configure_planner(runtime_config)
    configure_executor(runtime_config)
    configure_cloud_reliability(runtime_config)
    tighten_runtime_prompts(runtime_config)
    return runtime_config


def main() -> None:
    write_env_file(
        {
            "DEEPSEEK_API_KEY": require_env("DEEPSEEK_API_KEY"),
            "MINIMAX_API_KEY": require_env("MINIMAX_API_KEY"),
            "QWEN35_PLUS_API_KEY": require_env("QWEN35_PLUS_API_KEY"),
            "KIMI_K25_API_KEY": require_env("KIMI_K25_API_KEY"),
            "GLM51_API_KEY": require_env("GLM51_API_KEY"),
        }
    )
    runtime_config = build_runtime_config()
    TEMP_CONFIG_PATH.write_text(json.dumps(runtime_config, ensure_ascii=False, indent=2), encoding="utf-8")

    system = MASESystem(TEMP_CONFIG_PATH)
    models = system.describe_models()
    system.ask("请记住：我们公司的营销预算是350万元，线上投放占60%。", log=False)
    for index in range(2, 30):
        system.ask(f"闲聊第{index}轮：今天天气不错。", log=False)
    final_trace = system.run_with_trace("我们最开始聊的那个营销预算，是多少？线上投放占多少？", log=False)

    report = {
        "config_path": str(TEMP_CONFIG_PATH),
        "env_path": str(TEMP_ENV_PATH),
        "models": models,
        "final_answer": final_trace.answer,
        "route_action": final_trace.route.action,
        "executor_target": final_trace.executor_target,
        "memory_result_count": len(final_trace.search_results),
        "record_path": final_trace.record_path,
        "checks": {
            "answer_mentions_budget": "350" in final_trace.answer,
            "answer_mentions_ratio": "60" in final_trace.answer,
            "route_is_search_memory": final_trace.route.action == "search_memory",
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
