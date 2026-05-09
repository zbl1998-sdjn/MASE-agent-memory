import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { BarChart } from "../components/Charts";
import { DataTable } from "../components/DataTable";
import { JsonBlock } from "../components/JsonBlock";
import { StatCard } from "../components/StatCard";
import { StatusLine } from "../components/StatusLine";
import type { ChartPoint, JsonRecord, MaseResponse, ObservabilityData } from "../types";

const statTones = ["cyan", "violet", "green", "amber"] as const;

function counterPoints(record: Record<string, number> | undefined): ChartPoint[] {
  return Object.entries(record ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([name, value]) => ({ name, value }));
}

function formatUsd(value: number | undefined): string {
  if (!value) {
    return "$0.0000";
  }
  return `$${value.toFixed(4)}`;
}

export function ObservabilityPage() {
  const [payload, setPayload] = useState<MaseResponse<ObservabilityData>>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError("");
    api.observability(50)
      .then(setPayload)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const data = payload?.data;
  const totals = data?.model_ledger.totals ?? {};
  const eventCounters = useMemo(() => counterPoints(data?.metrics.event_counters), [data]);
  const latencyCounters = useMemo(() => counterPoints(data?.metrics.latency_ms_avg), [data]);
  const totalStats = [
    { label: "model calls", value: totals.call_count ?? 0, hint: "current process ledger" },
    { label: "total tokens", value: totals.total_tokens ?? 0, hint: "provider usage or estimate" },
    { label: "cloud calls", value: totals.cloud_call_count ?? 0, hint: "billable-risk calls" },
    { label: "estimated cost", value: formatUsd(totals.estimated_cost_usd), hint: "local models stay $0" }
  ];

  return (
    <div className="stack">
      <section className="hero-panel observability-hero">
        <div>
          <p className="eyebrow">Memory Observatory</p>
          <h1>成本、健康、事件与模型调用账本</h1>
          <p>用于定位回答错误、模型热插拔风险、云模型 token 成本和当前进程健康状态。</p>
          <div className="tag-list observability-tags">
            <span className="tag">{data?.mode.read_only ? "Read-only audit" : "Writable local mode"}</span>
            <span className="tag">{data?.mode.auth_required ? "API key protected writes" : "Local dev writes"}</span>
            <span className="tag">{data?.mode.frontend_static_ready ? "Static frontend ready" : "Dev frontend mode"}</span>
          </div>
        </div>
        <div className="hero-visual">
          <div className="metric-grid">
            <div className="metric">
              <span>configured agents</span>
              <strong>{Object.keys(data?.models ?? {}).length}</strong>
            </div>
            <div className="metric">
              <span>health rows</span>
              <strong>{data?.model_health.length ?? 0}</strong>
            </div>
            <div className="metric">
              <span>event topics</span>
              <strong>{Object.keys(data?.metrics.event_counters ?? {}).length}</strong>
            </div>
          </div>
        </div>
      </section>

      <StatusLine loading={loading} error={error} />

      <div className="stat-grid">
        {totalStats.map((item, index) => (
          <StatCard
            key={item.label}
            label={item.label}
            value={item.value}
            hint={item.hint}
            tone={statTones[index % statTones.length]}
          />
        ))}
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>Event bus counters</h2>
            <p>按 topic 聚合的运行事件，可定位链路是否触发。</p>
          </header>
          <BarChart data={eventCounters} emptyLabel="暂无 event bus 事件" />
        </section>
        <section className="glass-card">
          <header>
            <h2>Latency by topic</h2>
            <p>事件 payload 中携带 latency_ms 的平均延迟。</p>
          </header>
          <BarChart data={latencyCounters} emptyLabel="暂无 latency 采样" />
        </section>
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>Model health</h2>
            <p>候选模型成功率、EWMA 延迟和 cooldown 线索。</p>
          </header>
          <DataTable
            rows={data?.model_health ?? []}
            preferredColumns={["provider", "model", "success_rate", "latency_ms_ewma", "consecutive_failures", "total_calls"]}
          />
        </section>
        <section className="glass-card">
          <header>
            <h2>Cost by agent</h2>
            <p>从模型调用 ledger 聚合 token 与估算成本。</p>
          </header>
          <DataTable
            rows={data?.model_ledger.by_agent ?? []}
            preferredColumns={["name", "call_count", "total_tokens", "estimated_cost_usd"]}
          />
        </section>
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>Cost by model</h2>
            <p>热插拔后看清 provider/model 的调用分布。</p>
          </header>
          <DataTable
            rows={data?.model_ledger.by_model ?? []}
            preferredColumns={["name", "call_count", "total_tokens", "estimated_cost_usd"]}
          />
        </section>
        <section className="glass-card">
          <header>
            <h2>Recent model calls</h2>
            <p>安全摘要：不包含 prompt、raw response 或密钥。</p>
          </header>
          <DataTable
            rows={(data?.model_ledger.recent_calls ?? []) as JsonRecord[]}
            preferredColumns={[
              "created_at",
              "agent_role",
              "provider",
              "model_name",
              "is_local",
              "total_tokens",
              "estimated_cost_usd",
              "fallback_from",
              "fallback_to"
            ]}
          />
        </section>
      </div>

      <details className="debug-panel">
        <summary>Raw observability payload</summary>
        <JsonBlock value={payload ?? {}} filename="mase-observability.json" />
      </details>
    </div>
  );
}
