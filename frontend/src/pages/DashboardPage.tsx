import { useEffect, useState } from "react";
import { api } from "../api";
import { BarChart, DonutStat, Sparkline } from "../components/Charts";
import { DataTable } from "../components/DataTable";
import { JsonBlock } from "../components/JsonBlock";
import { StatCard } from "../components/StatCard";
import { StatusLine } from "../components/StatusLine";
import type { BootstrapData, DashboardData, JsonRecord, MaseResponse, Scope } from "../types";

type DashboardPageProps = {
  scope: Scope;
};

const statTones = ["cyan", "violet", "green", "amber"] as const;

export function DashboardPage({ scope }: DashboardPageProps) {
  const [health, setHealth] = useState<MaseResponse<JsonRecord>>();
  const [bootstrap, setBootstrap] = useState<MaseResponse<BootstrapData>>();
  const [dashboard, setDashboard] = useState<MaseResponse<DashboardData>>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

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
      <section className="hero-panel">
        <div>
          <p className="eyebrow">MASE Memory Platform</p>
          <h1>{product?.name ?? "White-box memory operations cockpit"}</h1>
          <p>{product?.tagline ?? "把 Agent 记忆变成可审计、可治理、可部署的产品平台。"}</p>
          <div className="hero-actions">
            {(dashboard?.data.quick_actions ?? product?.quick_actions ?? []).map((action) => (
              <a className="action-pill" href={action.target} key={action.label}>
                <strong>{action.label}</strong>
                <span>{action.description}</span>
              </a>
            ))}
          </div>
        </div>
        <div className="hero-visual">
          <DonutStat value={sourceFacts} total={Math.max(1, factTotal + eventTotal)} label="current facts share" />
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
            hint={key === "threads" ? "active memory threads" : "scope-aware"}
            tone={statTones[index % statTones.length]}
          />
        ))}
      </div>

      <div className="grid three">
        <section className="glass-card wide">
          <header>
            <h2>Memory distribution</h2>
            <p>Entity Fact Sheet 分类分布</p>
          </header>
          <BarChart data={dashboard?.data.charts.facts_by_category ?? []} />
        </section>
        <section className="glass-card">
          <header>
            <h2>Event roles</h2>
            <p>流水账角色占比</p>
          </header>
          <BarChart data={dashboard?.data.charts.events_by_role ?? []} />
        </section>
        <section className="glass-card">
          <header>
            <h2>Top threads</h2>
            <p>最近活跃主题</p>
          </header>
          <BarChart data={dashboard?.data.charts.events_by_thread ?? []} />
        </section>
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>System map</h2>
            <p>运行链路与可观测节点</p>
          </header>
          <div className="system-map">
            {(dashboard?.data.system_map ?? []).map((node, index) => (
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
            <h2>Product readiness</h2>
            <p>产品能力与部署状态</p>
          </header>
          <div className="feature-grid">
            {(product?.features ?? []).map((feature) => (
              <article key={feature.title}>
                <strong>{feature.title}</strong>
                <p>{feature.description}</p>
              </article>
            ))}
            <article>
              <strong>Static frontend</strong>
              <p>{product?.frontend_static_ready ? "FastAPI is serving frontend/dist." : "Run npm run build to enable single-process serving."}</p>
            </article>
          </div>
        </section>
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>Recent activity</h2>
            <p>最近流水账</p>
          </header>
          <DataTable
            rows={dashboard?.data.recent_activity ?? []}
            preferredColumns={["id", "thread_id", "role", "content", "event_timestamp"]}
          />
        </section>
        <section className="glass-card">
          <header>
            <h2>Top facts</h2>
            <p>当前事实快照</p>
          </header>
          <DataTable
            rows={dashboard?.data.top_facts ?? []}
            preferredColumns={["category", "entity_key", "entity_value", "updated_at"]}
          />
        </section>
      </div>

      <details className="debug-panel">
        <summary>Raw platform payload</summary>
        <JsonBlock value={{ health, bootstrap, dashboard }} filename="mase-platform-dashboard.json" />
      </details>
    </div>
  );
}
