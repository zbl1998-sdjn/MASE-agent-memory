import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { DataTable } from "../components/DataTable";
import { JsonBlock } from "../components/JsonBlock";
import { StatCard } from "../components/StatCard";
import { StatusLine } from "../components/StatusLine";
import type { CostPricingData, CostRoutingData, CostSummaryData, JsonRecord, MaseResponse } from "../types";

const statTones = ["cyan", "violet", "green", "amber"] as const;

function asNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function formatUsd(value: unknown): string {
  const amount = asNumber(value);
  return `$${amount.toFixed(4)}`;
}

function formatPercent(value: unknown): string {
  return `${(asNumber(value) * 100).toFixed(1)}%`;
}

function sortedHighCostEvents(rows: JsonRecord[]): JsonRecord[] {
  return [...rows]
    .filter((row) => typeof row.estimated_cost_usd === "number")
    .sort((a, b) => asNumber(b.estimated_cost_usd) - asNumber(a.estimated_cost_usd))
    .slice(0, 10);
}

export function CostCenterPage() {
  const [pricingPayload, setPricingPayload] = useState<MaseResponse<CostPricingData>>();
  const [routingPayload, setRoutingPayload] = useState<MaseResponse<CostRoutingData>>();
  const [summaryPayload, setSummaryPayload] = useState<MaseResponse<CostSummaryData>>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    setError("");
    Promise.all([api.costPricing(), api.costRouting(), api.costSummary(100)])
      .then(([pricing, routing, summary]) => {
        setPricingPayload(pricing);
        setRoutingPayload(routing);
        setSummaryPayload(summary);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const pricing = pricingPayload?.data;
  const routing = routingPayload?.data;
  const summary = summaryPayload?.data;
  const totals = summary?.totals ?? {};
  const coverage = summary?.pricing_coverage;
  const highCostEvents = useMemo(() => sortedHighCostEvents(summary?.recent_events ?? []), [summary]);
  const unpricedModels = (coverage?.unpriced_models ?? []) as JsonRecord[];
  const metadata = pricingPayload?.metadata ?? {};
  const warnings = Array.isArray(metadata.warnings) ? metadata.warnings : [];
  const statItems = [
    { label: "estimated cost", value: formatUsd(totals.estimated_cost_usd), hint: "catalog-priced calls only" },
    { label: "cloud calls", value: totals.cloud_call_count ?? 0, hint: "local providers stay free" },
    { label: "unpriced calls", value: summary?.unpriced_call_count ?? 0, hint: "cloud calls missing catalog price" },
    { label: "routing warnings", value: routing?.summary.warning_count ?? 0, hint: routing?.policy ?? "warn_only" }
  ];

  return (
    <div className="stack">
      <section className="hero-panel cost-hero">
        <div>
          <p className="eyebrow">Cost Center</p>
          <h1>云模型费用、定价覆盖与未定价风险</h1>
          <p>把热插拔模型调用账本转成可解释费用视图：本地模型免费、云模型必须有价格源，未定价绝不默认为 $0。</p>
          <div className="tag-list">
            <span className="tag">policy: {pricing?.status.policy ?? coverage?.policy ?? "warn_only"}</span>
            <span className="tag">catalog items: {pricing?.status.catalog_item_count ?? coverage?.catalog_item_count ?? 0}</span>
            <span className="tag">
              cloud default $0: {pricing?.status.cloud_calls_default_to_zero === false ? "blocked" : "risk"}
            </span>
          </div>
        </div>
        <div className="hero-visual">
          <div className="metric-grid">
            <div className="metric">
              <span>priced calls</span>
              <strong>{coverage?.priced_call_count ?? 0}</strong>
            </div>
            <div className="metric">
              <span>local free calls</span>
              <strong>{coverage?.local_free_call_count ?? 0}</strong>
            </div>
            <div className="metric">
              <span>recent events</span>
              <strong>{summary?.recent_events.length ?? 0}</strong>
            </div>
          </div>
        </div>
      </section>

      <StatusLine loading={loading} error={error} />

      {(metadata.missing_file || warnings.length > 0 || (summary?.warning_count ?? 0) > 0) && (
        <section className="cost-warning">
          <strong>Cost governance warning</strong>
          <p>
            {metadata.missing_file
              ? "Pricing catalog is missing. Cloud calls remain visible as unpriced instead of being counted as free."
              : "Some cloud calls or catalog entries need pricing review."}
          </p>
          {warnings.length > 0 && <pre>{warnings.join("\n")}</pre>}
        </section>
      )}

      <div className="stat-grid">
        {statItems.map((item, index) => (
          <StatCard key={item.label} label={item.label} value={item.value} hint={item.hint} tone={statTones[index]} />
        ))}
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>Pricing catalog</h2>
            <p>当前启用的 provider/model 价格源。只读展示，避免误编辑影响账本解释。</p>
          </header>
          <DataTable
            rows={pricing?.catalog ?? []}
            preferredColumns={[
              "provider",
              "model_name",
              "input_cost_per_1k_tokens",
              "output_cost_per_1k_tokens",
              "cost_per_1k_tokens",
              "currency",
              "source",
              "enabled"
            ]}
          />
        </section>
        <section className="glass-card">
          <header>
            <h2>Unpriced cloud models</h2>
            <p>这些云端调用不会被计为 $0，需要补价格或明确预算豁免。</p>
          </header>
          <DataTable rows={unpricedModels} preferredColumns={["provider", "model_name", "call_count", "total_tokens"]} />
        </section>
      </div>

      <section className="glass-card">
        <header>
          <h2>Cost-aware routing readiness</h2>
          <p>后端策略 hook 已覆盖每个 agent/mode；当前只解释 allow / warn / blocked，不擅自改模型选择。</p>
        </header>
        <div className="cost-coverage">
          <span>pricing coverage: {formatPercent(coverage?.coverage_ratio)}</span>
          <span>cloud allowed: {routing?.cloud_models_allowed ? "yes" : "no"}</span>
          <span>blocked routes: {routing?.summary.blocked_count ?? 0}</span>
          <span>unpriced routes: {routing?.summary.unpriced_count ?? 0}</span>
        </div>
        <DataTable
          rows={routing?.routes ?? []}
          preferredColumns={[
            "agent_type",
            "mode",
            "provider",
            "model_name",
            "action",
            "status",
            "pricing_status",
            "pricing_type",
            "warnings"
          ]}
        />
      </section>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>Cost by model</h2>
            <p>定位哪个 provider/model 贡献了 token、费用或未定价风险。</p>
          </header>
          <DataTable
            rows={summary?.by_model ?? []}
            preferredColumns={[
              "name",
              "call_count",
              "priced_call_count",
              "unpriced_call_count",
              "total_tokens",
              "estimated_cost_usd",
              "ledger_estimated_cost_usd"
            ]}
          />
        </section>
        <section className="glass-card">
          <header>
            <h2>Cost by agent role</h2>
            <p>看清 router、notetaker、executor 等角色的费用责任边界。</p>
          </header>
          <DataTable
            rows={summary?.by_agent ?? []}
            preferredColumns={[
              "name",
              "call_count",
              "priced_call_count",
              "unpriced_call_count",
              "total_tokens",
              "estimated_cost_usd"
            ]}
          />
        </section>
      </div>

      <div className="grid two">
        <section className="glass-card">
          <header>
            <h2>High-cost recent calls</h2>
            <p>按 catalog 估算费用倒序，快速定位费用尖刺。</p>
          </header>
          <DataTable
            rows={highCostEvents}
            preferredColumns={[
              "created_at",
              "agent_role",
              "provider",
              "model_name",
              "total_tokens",
              "estimated_cost_usd",
              "pricing_source"
            ]}
          />
        </section>
        <section className="glass-card">
          <header>
            <h2>Budget rules</h2>
            <p>预算规则目前为 warn-only 展示，后续 Cost-aware Routing 再接入执行策略。</p>
          </header>
          <DataTable rows={pricing?.budget_rules ?? []} preferredColumns={["name", "monthly_usd", "daily_usd", "scope"]} />
        </section>
      </div>

      <section className="glass-card">
        <header>
          <h2>Recent pricing events</h2>
          <p>安全摘要：不包含 prompt、response、headers 或 token，只保留费用排查需要的字段。</p>
        </header>
        <DataTable
          rows={summary?.recent_events ?? []}
          preferredColumns={[
            "created_at",
            "agent_role",
            "provider",
            "model_name",
            "pricing_status",
            "pricing_type",
            "prompt_tokens",
            "completion_tokens",
            "estimated_cost_usd",
            "ledger_estimated_cost_usd"
          ]}
        />
      </section>

      <details className="debug-panel">
        <summary>Raw cost center payload</summary>
        <JsonBlock
          value={{ pricing: pricingPayload ?? {}, routing: routingPayload ?? {}, summary: summaryPayload ?? {} }}
          filename="mase-cost-center.json"
        />
      </details>
    </div>
  );
}
