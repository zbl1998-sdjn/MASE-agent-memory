from __future__ import annotations

REPRESENTATIVE_BATTLEFIELDS = [
    {
        "id": "memory-updated-port",
        "battlefield": "long_memory",
        "title": "更新后事实回忆",
        "kind": "conversation",
        "expected_fragments": ["9912", "灰度入口"],
        "turns": [
            "请记住：演示环境 API 网关当前走 9909 端口，9910 是灰度入口。",
            "请用两句话解释为什么多人协作时接口命名要统一。",
            "请记住：刚才那条端口信息更新一下，正式入口改成 9912，9910 仍然是灰度入口。",
            "写一个 Python 函数校验端口号是否合法。",
        ],
        "final_question": "把我们前面确认过的正式 API 网关端口再说一遍，并提醒我别和灰度入口混淆。",
    },
    {
        "id": "memory-budget-structure",
        "battlefield": "long_memory",
        "title": "多数字事实回忆",
        "kind": "conversation",
        "expected_fragments": ["420", "45%"],
        "turns": [
            "请记住：Q3 的内容营销预算总额是 420 万元，其中短视频种草占 45%，效果广告占 35%。",
            "如果一个团队要决定是用 webhook 还是轮询同步订单状态，你会怎么比较它们的适用场景？",
            "请把“先验证假设，再扩大投入”改写成更适合给老板看的汇报口吻。",
        ],
        "final_question": "我们之前记录的 Q3 内容营销预算总额是多少，短视频种草占比又是多少？",
    },
    {
        "id": "knowledge-rag-vs-long-context",
        "battlefield": "general_reasoning",
        "title": "通用知识解释",
        "kind": "single_turn",
        "expected_fragments": ["RAG", "长上下文"],
        "question": "请用简洁中文解释 RAG 和长上下文的区别，各说一个优点。",
    },
    {
        "id": "expert-risk-threshold",
        "battlefield": "expert_reasoning",
        "title": "业务专家推理",
        "kind": "single_turn",
        "expected_fragments": ["误报", "漏报"],
        "question": "请比较退款预警阈值设置得过高和过低，各自最容易带来的业务风险。回答里请同时提到误报和漏报。",
    },
    {
        "id": "code-port-validator",
        "battlefield": "code_generation",
        "title": "代码生成",
        "kind": "single_turn",
        "expected_fragments": ["def", "1024", "65535"],
        "question": "写一个 Python 函数，用来校验端口号是否在 1024 到 65535 的合法范围内。",
    },
    {
        "id": "math-word-problem",
        "battlefield": "math",
        "title": "多步数学推理",
        "kind": "single_turn",
        "expected_fragments": ["63"],
        "question": "一个团队第一周解决了 18 个问题，第二周解决的数量比第一周多 6 个，第三周是前两周总和的一半。三周一共解决了多少个问题？请给出最终答案。",
    },
]
