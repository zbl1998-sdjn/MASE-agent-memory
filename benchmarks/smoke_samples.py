from __future__ import annotations

from .schemas import BenchmarkSample, BenchmarkTurn

SMOKE_SAMPLES = {
    "generalization_smoke": [
        BenchmarkSample(
            id="synthetic-memory-update-001",
            benchmark="generalization_smoke",
            task_type="long_memory",
            question="Which relay station is active now?",
            ground_truth="Juniper-7",
            history=[
                BenchmarkTurn(role="user", content="The active relay station is Alder-4. Juniper-7 is only the fallback."),
                BenchmarkTurn(role="assistant", content="Noted: Alder-4 is active and Juniper-7 is fallback."),
                BenchmarkTurn(role="user", content="Update the relay plan: Juniper-7 is now active, Alder-4 is retired."),
                BenchmarkTurn(role="assistant", content="Updated: Juniper-7 is active and Alder-4 is retired."),
            ],
            answer_keywords=["Juniper-7"],
            word_blacklist=["Alder-4"],
        ),
        BenchmarkSample(
            id="synthetic-context-distractor-001",
            benchmark="generalization_smoke",
            task_type="long_context_qa",
            question="Which warehouse code should receive the blue crates?",
            ground_truth="WH-42",
            context=(
                "Dispatch notes:\n"
                "- Red crates were first assigned to WH-17, then cancelled.\n"
                "- Blue crates were briefly listed under WH-18 in a draft manifest.\n"
                "- Final manifest: blue crates go to WH-42; green crates go to WH-18.\n"
                "- Do not use draft manifest entries for final routing."
            ),
            answer_keywords=["WH-42"],
            word_blacklist=["WH-18"],
        ),
        BenchmarkSample(
            id="synthetic-transfer-math-001",
            benchmark="generalization_smoke",
            task_type="math",
            question="A lab validated 14 samples on Monday, twice as many on Tuesday, and 9 fewer on Wednesday than Tuesday. How many samples were validated in total?",
            ground_truth="61",
            answer_keywords=["61"],
        ),
    ],
    "longmemeval_smoke": [
        BenchmarkSample(
            id="longmemeval-smoke-001",
            benchmark="longmemeval_smoke",
            task_type="long_memory",
            question="我们之前确认过的正式 API 网关端口是多少？",
            ground_truth="9912",
            history=[
                BenchmarkTurn(role="user", content="请记住：演示环境 API 网关当前走 9909 端口，9910 是灰度入口。"),
                BenchmarkTurn(role="assistant", content="好的，我记住了，正式入口是 9909，灰度入口是 9910。"),
                BenchmarkTurn(role="user", content="请记住：刚才那条端口信息更新一下，正式入口改成 9912，9910 仍然是灰度入口。"),
                BenchmarkTurn(role="assistant", content="收到，已更新为正式入口 9912，灰度入口 9910。"),
            ],
            answer_keywords=["9912"],
        )
    ],
    "lveval_smoke": [
        BenchmarkSample(
            id="lveval-smoke-001",
            benchmark="lveval_smoke",
            task_type="long_context_qa",
            question="根据上下文，正式 API 网关端口是多少？",
            ground_truth="9912",
            context=(
                "系统变更记录：\n"
                "1. 初始版本中，演示环境 API 网关使用 9909 端口，9910 用于灰度入口。\n"
                "2. 第二次变更中，正式入口从 9909 调整为 9912，灰度入口仍保持 9910。\n"
                "3. 运维备注：调用正式链路时请勿与灰度入口混淆。"
            ),
            answer_keywords=["9912"],
            word_blacklist=["的", "是", "根据", "上下文"],
        )
    ],
    "mmlu_smoke": [
        BenchmarkSample(
            id="mmlu-smoke-001",
            benchmark="mmlu_smoke",
            task_type="multiple_choice",
            question="下列哪个选项最符合 RAG 的特点？\nA. 只依赖模型参数记忆\nB. 检索外部知识后再生成\nC. 完全不使用上下文\nD. 只适用于图像任务",
            ground_truth="B",
            options=[
                "A. 只依赖模型参数记忆",
                "B. 检索外部知识后再生成",
                "C. 完全不使用上下文",
                "D. 只适用于图像任务",
            ],
            metadata={"correct_option_text": "检索外部知识后再生成"},
        )
    ],
    "gsm8k_smoke": [
        BenchmarkSample(
            id="gsm8k-smoke-001",
            benchmark="gsm8k_smoke",
            task_type="math",
            question="一个团队第一周解决了 18 个问题，第二周比第一周多 6 个，第三周是前两周总和的一半。三周一共解决了多少个问题？",
            ground_truth="63",
            answer_keywords=["63"],
        )
    ],
    "humaneval_smoke": [
        BenchmarkSample(
            id="humaneval-smoke-001",
            benchmark="humaneval_smoke",
            task_type="code_generation",
            question="请实现函数 `add(a, b)`，返回两个整数之和，只输出 Python 代码。",
            ground_truth="def add(a, b):\n    return a + b",
            answer_keywords=["def add", "return a + b"],
            entry_point="add",
        )
    ],
}
