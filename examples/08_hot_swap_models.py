"""
MASE 2.0 — Example 08: Hot-Swap Models via env vars
一行 env 把执行模型从本地 7B 切到云端 GLM-5, 无需改代码.

跑法:
    # 默认本地 7B
    python examples/08_hot_swap_models.py

    # 切到 GLM-5 (需 .env 中配 ZHIPU_API_KEY)
    $env:MASE_CONFIG_PATH = "config.lme_glm5.json"
    python examples/08_hot_swap_models.py

    # 跨厂商兜底链 (GLM-5 → kimi → deepseek → 本地 7B), 全部 env-gate
    $env:MASE_CONFIG_PATH = "config.lveval_glm5_swap.json"
    python examples/08_hot_swap_models.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mase import describe_models, mase_ask, reload_system  # noqa: E402


def main() -> None:
    cfg = os.environ.get("MASE_CONFIG_PATH", str(ROOT / "config.json"))
    print(f"[hot-swap] 使用配置: {cfg}\n")
    reload_system(config_path=cfg)
    models = describe_models()
    print("当前激活的角色 → 模型映射:")
    for role, info in sorted(models.items())[:10]:
        print(f"  {role:30s} → {info.get('provider', '?')}::{info.get('model', '?')}")
    print()
    q = "用一句话解释什么是 MASE."
    print(f"Q: {q}")
    print(f"A: {mase_ask(q)}")
    print("\n切换底层模型: 改 MASE_CONFIG_PATH, 不需要改任何代码.")


if __name__ == "__main__":
    main()
