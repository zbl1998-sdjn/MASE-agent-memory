import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { BarChart } from "../components/Charts";
import { DataTable } from "../components/DataTable";
import { JsonBlock } from "../components/JsonBlock";
import { StatCard } from "../components/StatCard";
import { StatusLine } from "../components/StatusLine";
import { type Lang, translations } from "../i18n";
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

type ObservabilityPageProps = {
  lang: Lang;
};

export function ObservabilityPage({ lang }: ObservabilityPageProps) {
  const [payload, setPayload] = useState<MaseResponse<ObservabilityData>>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const t = translations[lang].pages.observability;

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
    { label: t.stats.calls, value: totals.call_count ?? 0, hint: t.stats.callsHint },
    { label: t.stats.tokens, value: totals.total_tokens ?? 0, hint: t.stats.tokensHint },
    { label: t.stats.cloud, value: totals.cloud_call_count ?? 0, hint: t.stats.cloudHint },
    { label: t.stats.cost, value: formatUsd(totals.estimated_cost_usd), hint: t.stats.costHint }
  ];

  return (
    <div className="stack">
      <section className="hero-panel split">
        <div>
          <p className="eyebrow">{t.eyebrow}</p>
          <h1>{t.title}</h1>
          <p>{t.subtitle}</p>
          <div className="tag-list" style={{ marginTop: "0.9rem" }}>
            <span className="tag">{data?.mode.read_only ? t.modes.readOnly : t.modes.writable}</span>
            <span className="tag">{data?.mode.auth_required ? t.modes.authed : t.modes.devWrite}</span>
            <span className="tag">{data?.mode.frontend_static_ready ? t.modes.staticReady : t.modes.devFrontend}</span>
          </div>
        </div>
        <div className="hero-visual">
          <div className="metric-grid">
            <div className="metric">
              <span>{t.sidekick.agents}</span>
              <strong>{Object.keys(data?.models ?? {}).length}</strong>
            </div>
            <div className="metric">
              <span>{t.sidekick.health}</span>
              <strong>{data?.model_health.length ?? 0}</strong>
            </div>
            <div className="metric">
              <span>{t.sidekick.topics}</span>
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
            <div>
              <h2>{t.sections.events.title}</h2>
              <p>{t.sections.events.desc}</p>
            </div>
          </header>
          <BarChart data={eventCounters} emptyLabel={t.empty.events} />
        </section>
        <section className="glass-card">
          <header>
            <div>
              <h2>{t.sections.latency.title}</h2>
              <p>{t.sections.latency.desc}</p>
            </div>
          </header>
          <BarChart data={latencyCounters} emptyLabel={t.empty.latency} />
        </section>
      </div>

      <section className="glass-card">
        <header>
          <div>
            <h2>{t.sections.health.title}</h2>
            <p>{t.sections.health.desc}</p>
          </div>
        </header>
        <DataTable
          rows={data?.model_health ?? []}
          preferredColumns={["provider", "model", "success_rate", "latency_ms_ewma", "consecutive_failures", "total_calls"]}
        />
      </section>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <div>
              <h2>{t.sections.costAgent.title}</h2>
              <p>{t.sections.costAgent.desc}</p>
            </div>
          </header>
          <DataTable
            rows={data?.model_ledger.by_agent ?? []}
            preferredColumns={["name", "call_count", "total_tokens", "estimated_cost_usd"]}
          />
        </section>
        <section className="glass-card">
          <header>
            <div>
              <h2>{t.sections.costModel.title}</h2>
              <p>{t.sections.costModel.desc}</p>
            </div>
          </header>
          <DataTable
            rows={data?.model_ledger.by_model ?? []}
            preferredColumns={["name", "call_count", "total_tokens", "estimated_cost_usd"]}
          />
        </section>
      </div>

      <section className="glass-card">
        <header>
          <div>
            <h2>{t.sections.recent.title}</h2>
            <p>{t.sections.recent.desc}</p>
          </div>
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

      <details className="debug-panel">
        <summary>{translations[lang].common.rawPayload}</summary>
        <JsonBlock value={payload ?? {}} filename="mase-observability.json" />
      </details>
    </div>
  );
}
