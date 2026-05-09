import { useEffect, useMemo, useState } from "react";
import { api, getInternalApiKey, saveInternalApiKey } from "./api";
import { type Lang, detectDefaultLang, saveLang, translations } from "./i18n";
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

type NavGroup = "Overview" | "Reliability" | "Operations" | "Memory";

type NavBase = { key: NavKey; group: NavGroup; icon: string };

const NAV_BASE: NavBase[] = [
  { key: "dashboard",        group: "Overview",     icon: "01" },
  { key: "observability",    group: "Overview",     icon: "02" },
  { key: "cost",             group: "Overview",     icon: "03" },
  { key: "audit",            group: "Operations",   icon: "04" },
  { key: "privacy",          group: "Operations",   icon: "05" },
  { key: "lifecycle",        group: "Operations",   icon: "06" },
  { key: "quality",          group: "Reliability",  icon: "07" },
  { key: "answer-support",   group: "Reliability",  icon: "08" },
  { key: "refusal-quality",  group: "Reliability",  icon: "09" },
  { key: "why-not",          group: "Reliability",  icon: "10" },
  { key: "synthetic-replay", group: "Reliability",  icon: "11" },
  { key: "golden-tests",     group: "Reliability",  icon: "12" },
  { key: "slo-dashboard",    group: "Reliability",  icon: "13" },
  { key: "drift",            group: "Reliability",  icon: "14" },
  { key: "incidents",        group: "Operations",   icon: "15" },
  { key: "repair",           group: "Operations",   icon: "16" },
  { key: "chat",             group: "Memory",       icon: "17" },
  { key: "recall",           group: "Memory",       icon: "18" },
  { key: "facts",            group: "Memory",       icon: "19" },
  { key: "timeline",         group: "Memory",       icon: "20" },
  { key: "sessions",         group: "Memory",       icon: "21" },
  { key: "procedures",       group: "Memory",       icon: "22" },
];

const navGroups: NavGroup[] = ["Overview", "Reliability", "Operations", "Memory"];

function readHash(): NavKey {
  const key = window.location.hash.replace("#", "") as NavKey;
  return NAV_BASE.some((item) => item.key === key) ? key : "dashboard";
}

export default function App() {
  const [active, setActive] = useState<NavKey>(readHash);
  const [scope, setScope] = useState<Scope>(() => readStoredScope());
  const [categories, setCategories] = useState<string[]>([]);
  const [apiKey, setApiKey] = useState(() => getInternalApiKey());
  const [platformMode, setPlatformMode] = useState({ authRequired: false, readOnly: false });
  const [lang, setLang] = useState<Lang>(detectDefaultLang);

  const t = translations[lang];

  const navItems = NAV_BASE.map((item) => ({
    ...item,
    label: t.nav.items[item.key].label,
    description: t.nav.items[item.key].description,
  }));

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

  function toggleLang() {
    const next: Lang = lang === "zh" ? "en" : "zh";
    setLang(next);
    saveLang(next);
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
            <p>{t.brand}</p>
          </div>
        </div>
        <div className="sidebar-card">
          <span className="live-dot" />
          <div>
            <strong>{platformMode.readOnly ? t.readOnlyAudit : t.localProduct}</strong>
            <p>{platformMode.authRequired ? t.apiKeyRequired : t.fastApiReact}</p>
          </div>
        </div>
        <div className="sidebar-card vertical">
          <label>
            {t.internalApiKey}
            <input
              type="password"
              value={apiKey}
              placeholder={platformMode.authRequired ? t.apiKeyPlaceholder.required : t.apiKeyPlaceholder.optional}
              onChange={(event) => updateApiKey(event.target.value)}
            />
          </label>
          {platformMode.readOnly && <p className="mode-note">{t.readOnlyNote}</p>}
        </div>
        <nav className="nav-stack" aria-label="MASE product navigation">
          {navGroups.map((group) => (
            <section className="nav-section" key={group}>
              <p>{t.nav.groups[group]}</p>
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
            <p className="eyebrow">{t.localApi} · {apiLabel}</p>
            <h2>{activeItem?.label}</h2>
            <span>{activeItem?.description}</span>
          </div>
          <div className="topbar-actions">
            <button className="lang-toggle" onClick={toggleLang} title="Switch language / 切换语言">
              {t.langToggle}
            </button>
            <ScopeBar scope={scope} onChange={setScope} />
          </div>
        </header>
        {platformMode.readOnly && (
          <div className="mode-banner">{t.readOnlyBanner}</div>
        )}
        <ScopeGuard scope={scope} />
        {page}
      </main>
    </div>
  );
}
