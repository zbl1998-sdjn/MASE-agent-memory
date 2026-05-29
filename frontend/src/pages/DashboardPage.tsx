import { useEffect, useState } from "react";
import { api } from "../api";
import { BarChart, DonutStat, Sparkline } from "../components/Charts";
import { DataTable } from "../components/DataTable";
import { JsonBlock } from "../components/JsonBlock";
import { StatCard } from "../components/StatCard";
import { StatusLine } from "../components/StatusLine";
import { type Lang, translations } from "../i18n";
import type { BootstrapData, DashboardData, JsonRecord, MaseResponse, Scope } from "../types";

type DashboardPageProps = {
  scope: Scope;
  lang: Lang;
};

const statTones = ["cyan", "violet", "green", "amber"] as const;

export function DashboardPage({ scope, lang }: DashboardPageProps) {
  const [health, setHealth] = useState<MaseResponse<JsonRecord>>();
  const [bootstrap, setBootstrap] = useState<MaseResponse<BootstrapData>>();
  const [dashboard, setDashboard] = useState<MaseResponse<DashboardData>>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const t = translations[lang].pages.dashboard;

  useEffect(() => {
    setLoading(true);
    setError("");
    Promise.all([api.health(), api.bootstrap(), api.dashboard(scope)])
      .then(([healthData, bootstrapData, dashboardData]) => {
        setHealth(healthData);
        setBootstrap(bootstrapData);
        setDashboard(dashboardData);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [scope]);

  const product = bootstrap?.data.product;
  const kpis = dashboard?.data.kpis ?? {};
  const factTotal = kpis.facts ?? 0;
  const eventTotal = kpis.events ?? 0;
  const sourceFacts = dashboard?.data.charts.source_counts.find((item) => item.name === "entity_state")?.value ?? 0;

  return (
    <div className="stack">
      <section className="hero-panel split">
        <div>
          <p className="eyebrow">{t.eyebrow}</p>
          <h1>{product?.name ?? t.title}</h1>
          <p>{product?.tagline ?? t.subtitle}</p>
          <div className="hero-actions">
            {(dashboard?.data.quick_actions ?? product?.quick_actions ?? []).slice(0, 4).map((action) => (
              <a className="action-pill" href={action.target} key={action.label}>
                <strong>{action.label}</strong>
                <span>{action.description}</span>
              </a>
            ))}
          </div>
        </div>
        <div className="hero-visual">
          <DonutStat value={sourceFacts} total={Math.max(1, factTotal + eventTotal)} label={t.donut} />
          <Sparkline data={dashboard?.data.charts.activity_by_day ?? []} />
        </div>
      </section>

      <StatusLine loading={loading} error={error} />

      <div className="stat-grid">
        {Object.entries(kpis).map(([key, value], index) => (
          <StatCard
            key={key}
            label={key}
            value={value}
            tone={statTones[index % statTones.length]}
          />
        ))}
      </div>

      <div className="grid three">
        <section className="glass-card">
          <header>
            <div>
              <h2>{t.sections.distribution.title}</h2>
              <p>{t.sections.distribution.desc}</p>
            </div>
          </header>
          <BarChart data={dashboard?.data.charts.facts_by_category ?? []} />
        </section>
        <section className="glass-card">
          <header>
            <div>
              <h2>{t.sections.eventRoles.title}</h2>
              <p>{t.sections.eventRoles.desc}</p>
            </div>
          </header>
          <BarChart data={dashboard?.data.charts.events_by_role ?? []} />
        </section>
        <section className="glass-card">
          <header>
            <div>
              <h2>{t.sections.topThreads.title}</h2>
              <p>{t.sections.topThreads.desc}</p>
            </div>
          </header>
          <BarChart data={dashboard?.data.charts.events_by_thread ?? []} />
        </section>
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <div>
              <h2>{t.sections.systemMap.title}</h2>
              <p>{t.sections.systemMap.desc}</p>
            </div>
          </header>
          <div className="system-map">
            {(dashboard?.data.system_map ?? []).slice(0, 6).map((node, index) => (
              <div className="system-node" key={node.name}>
                <span>{index + 1}</span>
                <div>
                  <strong>{node.name}</strong>
                  <small>{node.status}</small>
                  <p>{node.description}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
        <section className="glass-card">
          <header>
            <div>
              <h2>{t.sections.recent.title}</h2>
              <p>{t.sections.recent.desc}</p>
            </div>
          </header>
          <DataTable
            rows={dashboard?.data.recent_activity ?? []}
            preferredColumns={["thread_id", "role", "content", "event_timestamp"]}
          />
        </section>
      </div>

      <details className="debug-panel">
        <summary>{translations[lang].common.rawPayload}</summary>
        <JsonBlock value={{ health, bootstrap, dashboard }} filename="mase-platform-dashboard.json" />
      </details>
    </div>
  );
}
