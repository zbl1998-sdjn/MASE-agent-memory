import { useEffect, useMemo, useState } from "react";
import { api, getInternalApiKey, saveInternalApiKey } from "./api";
import { ScopeBar } from "./components/ScopeBar";
import { ScopeGuard } from "./components/ScopeGuard";
import { AuditLogPage } from "./pages/AuditLogPage";
import { AnswerSupportPage } from "./pages/AnswerSupportPage";
import { ChatPage } from "./pages/ChatPage";
import { CostCenterPage } from "./pages/CostCenterPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DriftPage } from "./pages/DriftPage";
import { FactsPage } from "./pages/FactsPage";
import { GoldenTestsPage } from "./pages/GoldenTestsPage";
import { IncidentsPage } from "./pages/IncidentsPage";
import { LifecyclePage } from "./pages/LifecyclePage";
import { ObservabilityPage } from "./pages/ObservabilityPage";
import { PrivacyPage } from "./pages/PrivacyPage";
import { ProceduresPage } from "./pages/ProceduresPage";
import { QualityPage } from "./pages/QualityPage";
import { RecallPage } from "./pages/RecallPage";
import { RefusalQualityPage } from "./pages/RefusalQualityPage";
import { RepairPage } from "./pages/RepairPage";
import { SessionsPage } from "./pages/SessionsPage";
import { SloDashboardPage } from "./pages/SloDashboardPage";
import { SyntheticReplayPage } from "./pages/SyntheticReplayPage";
import { TimelinePage } from "./pages/TimelinePage";
import { WhyNotRememberedPage } from "./pages/WhyNotRememberedPage";
import type { NavKey, Scope } from "./types";
import { readStoredScope, saveStoredScope } from "./utils";

const apiLabel = import.meta.env.VITE_API_BASE || window.location.origin;

type NavItem = {
  key: NavKey;
  label: string;
  description: string;
  group: "Overview" | "Reliability" | "Operations" | "Memory";
  icon: string;
};

const navItems: NavItem[] = [
  { key: "dashboard", label: "运营 cockpit", description: "指标 / 图表 / 系统地图", group: "Overview", icon: "01" },
  { key: "observability", label: "Memory Observatory", description: "成本 / 健康 / 事件", group: "Overview", icon: "02" },
  { key: "cost", label: "Cost Center", description: "定价 / 预算 / 云成本", group: "Overview", icon: "03" },
  { key: "audit", label: "Audit Log", description: "权限 / 写入 / 追责", group: "Operations", icon: "04" },
  { key: "privacy", label: "Privacy Guard", description: "脱敏 / 敏感记忆", group: "Operations", icon: "05" },
  { key: "lifecycle", label: "Lifecycle", description: "TTL / 契约 / 分层", group: "Operations", icon: "06" },
  { key: "quality", label: "Quality Score", description: "质量分 / 风险项", group: "Reliability", icon: "07" },
  { key: "answer-support", label: "Answer Support", description: "答案证据支撑", group: "Reliability", icon: "08" },
  { key: "refusal-quality", label: "Refusal Quality", description: "拒答 / 无证据", group: "Reliability", icon: "09" },
  { key: "why-not", label: "Why Not Remembered", description: "未记住诊断", group: "Reliability", icon: "10" },
  { key: "synthetic-replay", label: "Synthetic Replay", description: "合成记忆回放", group: "Reliability", icon: "11" },
  { key: "golden-tests", label: "Golden Tests", description: "黄金回归门禁", group: "Reliability", icon: "12" },
  { key: "slo-dashboard", label: "SLO Dashboard", description: "可靠性目标", group: "Reliability", icon: "13" },
  { key: "drift", label: "Drift Detector", description: "漂移 / 冲突", group: "Reliability", icon: "14" },
  { key: "incidents", label: "Incidents", description: "事件 / 插件", group: "Operations", icon: "15" },
  { key: "repair", label: "Repair Center", description: "Agent 修复工单", group: "Operations", icon: "16" },
  { key: "chat", label: "Trace Studio", description: "聊天、路由和审计链", group: "Memory", icon: "17" },
  { key: "recall", label: "Recall Lab", description: "召回、解释和证据", group: "Memory", icon: "18" },
  { key: "facts", label: "Fact Center", description: "事实治理与历史", group: "Memory", icon: "19" },
  { key: "timeline", label: "Timeline Ops", description: "流水账、纠错、快照", group: "Memory", icon: "20" },
  { key: "sessions", label: "Session Vault", description: "短期上下文与 TTL", group: "Memory", icon: "21" },
  { key: "procedures", label: "Procedure Hub", description: "规则与工作流记忆", group: "Memory", icon: "22" }
];

const navGroups: Array<NavItem["group"]> = ["Overview", "Reliability", "Operations", "Memory"];

function readHash(): NavKey {
  const key = window.location.hash.replace("#", "") as NavKey;
  return navItems.some((item) => item.key === key) ? key : "dashboard";
}

export default function App() {
  const [active, setActive] = useState<NavKey>(readHash);
  const [scope, setScope] = useState<Scope>(() => readStoredScope());
  const [categories, setCategories] = useState<string[]>([]);
  const [apiKey, setApiKey] = useState(() => getInternalApiKey());
  const [platformMode, setPlatformMode] = useState({ authRequired: false, readOnly: false });
  const activeItem = navItems.find((item) => item.key === active);

  useEffect(() => {
    const onHash = () => setActive(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    saveStoredScope(scope);
  }, [scope]);

  useEffect(() => {
    api.bootstrap()
      .then((response) => {
        setCategories(response.data.profile_templates);
        setPlatformMode({
          authRequired: response.data.product?.auth_required ?? false,
          readOnly: response.data.product?.read_only ?? false
        });
      })
      .catch(() => setCategories([]));
  }, []);

  function updateApiKey(value: string) {
    setApiKey(value);
    saveInternalApiKey(value);
  }

  const page = useMemo(() => {
    switch (active) {
      case "chat":
        return <ChatPage readOnly={platformMode.readOnly} />;
      case "observability":
        return <ObservabilityPage />;
      case "cost":
        return <CostCenterPage />;
      case "audit":
        return <AuditLogPage />;
      case "privacy":
        return <PrivacyPage scope={scope} />;
      case "lifecycle":
        return <LifecyclePage scope={scope} />;
      case "quality":
        return <QualityPage scope={scope} />;
      case "answer-support":
        return <AnswerSupportPage scope={scope} />;
      case "refusal-quality":
        return <RefusalQualityPage scope={scope} />;
      case "why-not":
        return <WhyNotRememberedPage scope={scope} />;
      case "synthetic-replay":
        return <SyntheticReplayPage scope={scope} />;
      case "golden-tests":
        return <GoldenTestsPage scope={scope} />;
      case "slo-dashboard":
        return <SloDashboardPage scope={scope} />;
      case "drift":
        return <DriftPage scope={scope} />;
      case "incidents":
        return <IncidentsPage scope={scope} />;
      case "repair":
        return <RepairPage scope={scope} />;
      case "recall":
        return <RecallPage scope={scope} />;
      case "facts":
        return <FactsPage scope={scope} categories={categories} readOnly={platformMode.readOnly} />;
      case "timeline":
        return <TimelinePage scope={scope} readOnly={platformMode.readOnly} />;
      case "sessions":
        return <SessionsPage scope={scope} readOnly={platformMode.readOnly} />;
      case "procedures":
        return <ProceduresPage scope={scope} readOnly={platformMode.readOnly} />;
      default:
        return <DashboardPage scope={scope} />;
    }
  }, [active, categories, platformMode.readOnly, scope]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">M</span>
          <div>
            <h1>MASE</h1>
            <p>Memory reliability console</p>
          </div>
        </div>
        <div className="sidebar-card">
          <span className="live-dot" />
          <div>
            <strong>{platformMode.readOnly ? "Read-only audit mode" : "Local product mode"}</strong>
            <p>{platformMode.authRequired ? "API key required for writes" : "FastAPI + React visual platform"}</p>
          </div>
        </div>
        <div className="sidebar-card vertical">
          <label>
            Internal API Key
            <input
              type="password"
              value={apiKey}
              placeholder={platformMode.authRequired ? "Required for write actions" : "Optional"}
              onChange={(event) => updateApiKey(event.target.value)}
            />
          </label>
          {platformMode.readOnly && <p className="mode-note">写入、删除、纠错、快照生成已由后端强制禁用。</p>}
        </div>
        <nav className="nav-stack" aria-label="MASE product navigation">
          {navGroups.map((group) => (
            <section className="nav-section" key={group}>
              <p>{group}</p>
              {navItems
                .filter((item) => item.group === group)
                .map((item) => (
                  <a className={active === item.key ? "active" : ""} href={`#${item.key}`} key={item.key}>
                    <span className="nav-index">{item.icon}</span>
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                  </a>
                ))}
            </section>
          ))}
        </nav>
      </aside>
      <main>
        <header className="topbar">
          <div className="topbar-title">
            <p className="eyebrow">Local API · {apiLabel}</p>
            <h2>{activeItem?.label}</h2>
            <span>{activeItem?.description}</span>
          </div>
          <ScopeBar scope={scope} onChange={setScope} />
        </header>
        {platformMode.readOnly && (
          <div className="mode-banner">Read-only audit mode：当前只能观察、检索和调试，所有持久写入已禁用。</div>
        )}
        <ScopeGuard scope={scope} />
        {page}
      </main>
    </div>
  );
}
