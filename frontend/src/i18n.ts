export type Lang = "zh" | "en";

export const translations = {
  zh: {
    brand: "记忆可靠性控制台",
    readOnlyAudit: "只读审计模式",
    localProduct: "本地产品模式",
    apiKeyRequired: "写入操作需要 API Key",
    fastApiReact: "FastAPI + React 可视化平台",
    internalApiKey: "内部 API Key",
    apiKeyPlaceholder: { required: "写入操作必填", optional: "可选" },
    readOnlyNote: "写入、删除、纠错、快照生成已由后端强制禁用。",
    readOnlyBanner: "只读审计模式：当前只能观察、检索和调试，所有持久写入已禁用。",
    localApi: "本地 API",
    langToggle: "EN",
    nav: {
      groups: {
        Overview: "总览",
        Reliability: "可靠性",
        Operations: "运营",
        Memory: "记忆",
      },
      items: {
        dashboard: { label: "运营 Cockpit", description: "指标 / 图表 / 系统地图" },
        observability: { label: "Memory 观测台", description: "成本 / 健康 / 事件" },
        cost: { label: "成本中心", description: "定价 / 预算 / 云成本" },
        audit: { label: "审计日志", description: "权限 / 写入 / 追责" },
        privacy: { label: "隐私防护", description: "脱敏 / 敏感记忆" },
        lifecycle: { label: "生命周期", description: "TTL / 契约 / 分层" },
        quality: { label: "质量评分", description: "质量分 / 风险项" },
        "answer-support": { label: "答案支撑", description: "答案证据支撑" },
        "refusal-quality": { label: "拒答质量", description: "拒答 / 无证据" },
        "why-not": { label: "为何未记住", description: "未记住诊断" },
        "synthetic-replay": { label: "合成回放", description: "合成记忆回放" },
        "golden-tests": { label: "黄金测试", description: "黄金回归门禁" },
        "slo-dashboard": { label: "SLO 看板", description: "可靠性目标" },
        drift: { label: "漂移检测", description: "漂移 / 冲突" },
        incidents: { label: "事件中心", description: "事件 / 插件" },
        repair: { label: "修复中心", description: "Agent 修复工单" },
        chat: { label: "Trace 工作室", description: "聊天、路由和审计链" },
        recall: { label: "召回实验室", description: "召回、解释和证据" },
        facts: { label: "事实中心", description: "事实治理与历史" },
        timeline: { label: "时间线", description: "流水账、纠错、快照" },
        sessions: { label: "会话库", description: "短期上下文与 TTL" },
        procedures: { label: "规则中枢", description: "规则与工作流记忆" },
      },
    },
  },
  en: {
    brand: "Memory reliability console",
    readOnlyAudit: "Read-only audit mode",
    localProduct: "Local product mode",
    apiKeyRequired: "API key required for writes",
    fastApiReact: "FastAPI + React visual platform",
    internalApiKey: "Internal API Key",
    apiKeyPlaceholder: { required: "Required for write actions", optional: "Optional" },
    readOnlyNote: "Write, delete, correction, and snapshot actions are disabled by backend.",
    readOnlyBanner: "Read-only audit mode: observe, search and debug only. All persistent writes are disabled.",
    localApi: "Local API",
    langToggle: "中",
    nav: {
      groups: {
        Overview: "Overview",
        Reliability: "Reliability",
        Operations: "Operations",
        Memory: "Memory",
      },
      items: {
        dashboard: { label: "Ops Cockpit", description: "Metrics / Charts / System Map" },
        observability: { label: "Memory Observatory", description: "Cost / Health / Events" },
        cost: { label: "Cost Center", description: "Pricing / Budget / Cloud Cost" },
        audit: { label: "Audit Log", description: "Permissions / Writes / Accountability" },
        privacy: { label: "Privacy Guard", description: "Redaction / Sensitive Memory" },
        lifecycle: { label: "Lifecycle", description: "TTL / Contracts / Tiering" },
        quality: { label: "Quality Score", description: "Quality Score / Risk Items" },
        "answer-support": { label: "Answer Support", description: "Answer Evidence Support" },
        "refusal-quality": { label: "Refusal Quality", description: "Refusal / No Evidence" },
        "why-not": { label: "Why Not Remembered", description: "Not Remembered Diagnosis" },
        "synthetic-replay": { label: "Synthetic Replay", description: "Synthetic Memory Replay" },
        "golden-tests": { label: "Golden Tests", description: "Regression Release Gate" },
        "slo-dashboard": { label: "SLO Dashboard", description: "Reliability Objectives" },
        drift: { label: "Drift Detector", description: "Drift / Conflicts" },
        incidents: { label: "Incidents", description: "Incidents / Plugins" },
        repair: { label: "Repair Center", description: "Agent Repair Tickets" },
        chat: { label: "Trace Studio", description: "Chat, Routing and Audit Chain" },
        recall: { label: "Recall Lab", description: "Recall, Explain and Evidence" },
        facts: { label: "Fact Center", description: "Fact Governance and History" },
        timeline: { label: "Timeline Ops", description: "Events, Corrections, Snapshots" },
        sessions: { label: "Session Vault", description: "Short-term Context and TTL" },
        procedures: { label: "Procedure Hub", description: "Rules and Workflow Memory" },
      },
    },
  },
} as const;

export type Translations = typeof translations.zh;

export function detectDefaultLang(): Lang {
  const stored = localStorage.getItem("mase_lang");
  if (stored === "zh" || stored === "en") return stored;
  return navigator.language.startsWith("zh") ? "zh" : "en";
}

export function saveLang(lang: Lang): void {
  localStorage.setItem("mase_lang", lang);
}
