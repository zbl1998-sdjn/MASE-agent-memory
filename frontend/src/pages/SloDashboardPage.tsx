import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { MaseResponse, Scope, SloDashboardData } from "../types";

type SloDashboardPageProps = {
  scope: Scope;
};

export function SloDashboardPage({ scope }: SloDashboardPageProps) {
  const [query, setQuery] = useState("project owner");
  const [expected, setExpected] = useState("Alice");
  const [report, setReport] = useState<MaseResponse<SloDashboardData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runSlo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const cases = [
        {
          case_id: "slo-smoke",
          query,
          expected_terms: expected.split(",").map((item) => item.trim()).filter(Boolean),
          severity: "critical"
        }
      ];
      setReport(await api.sloDashboard({ cases }, scope));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Memory SLO Dashboard" subtitle="聚合黄金测试、契约健康和成本定价覆盖率">
        <form className="inline-form" onSubmit={runSlo}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Golden query" />
          <input
            value={expected}
            onChange={(event) => setExpected(event.target.value)}
            placeholder="Expected terms, comma separated"
          />
          <button type="submit">刷新 SLO</button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <div className="grid cards-3">
            <Card title="Overall">{String(report.data.summary.overall_status ?? "unknown")}</Card>
            <Card title="Release gate">{String(report.data.summary.release_gate ?? "unknown")}</Card>
            <Card title="Breaches">{report.data.summary.breached_count ?? 0}</Card>
          </div>
          <Card title="Objectives">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Status</th>
                    <th>Value</th>
                    <th>Target</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.objectives.map((objective, index) => (
                    <tr key={index}>
                      <td>{String(objective.name ?? "")}</td>
                      <td>{String(objective.status ?? "")}</td>
                      <td>{String(objective.value ?? "")}</td>
                      <td>{String(objective.target ?? "")}</td>
                      <td>{String(objective.source ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="SLO payload">
            <JsonBlock value={report} filename="mase-slo-dashboard.json" />
          </Card>
        </>
      )}
    </div>
  );
}
