import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { GoldenTestsData, MaseResponse, Scope } from "../types";

type GoldenTestsPageProps = {
  scope: Scope;
};

const defaultCases = JSON.stringify(
  [
    {
      case_id: "owner-critical",
      category: "current_fact",
      severity: "critical",
      query: "project owner",
      expected_terms: ["Alice"],
      forbidden_terms: ["Bob"],
      min_quality_score: 0.8
    }
  ],
  null,
  2
);

export function GoldenTestsPage({ scope }: GoldenTestsPageProps) {
  const [casesJson, setCasesJson] = useState(defaultCases);
  const [report, setReport] = useState<MaseResponse<GoldenTestsData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runGolden(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const cases = JSON.parse(casesJson) as unknown;
      if (!Array.isArray(cases)) {
        throw new Error("Cases JSON must be an array");
      }
      setReport(await api.goldenTests({ cases }, scope));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Golden Memory Test Lab" subtitle="以关键用例作为发布门禁，阻断严重记忆回归">
        <form className="stack-form" onSubmit={runGolden}>
          <label>
            Golden cases JSON
            <textarea rows={12} value={casesJson} onChange={(event) => setCasesJson(event.target.value)} />
          </label>
          <button type="submit">运行黄金测试</button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <div className="grid cards-3">
            <Card title="Release gate">{String(report.data.summary.release_gate ?? "unknown")}</Card>
            <Card title="Pass rate">{String(report.data.summary.pass_rate ?? 0)}</Card>
            <Card title="Critical failures">{report.data.summary.critical_failed_count ?? 0}</Card>
          </div>
          <Card title="Golden results">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Category</th>
                    <th>Severity</th>
                    <th>Verdict</th>
                    <th>Quality</th>
                    <th>Missing</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.results.map((result, index) => (
                    <tr key={index}>
                      <td>{String(result.case_id ?? "")}</td>
                      <td>{String(result.category ?? "")}</td>
                      <td>{String(result.severity ?? "")}</td>
                      <td>{String(result.verdict ?? "")}</td>
                      <td>{String(result.quality_score ?? 0)}</td>
                      <td>{String((result.missing_expected_terms as string[] | undefined)?.join(", ") ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Golden payload">
            <JsonBlock value={report} filename="mase-golden-tests.json" />
          </Card>
        </>
      )}
    </div>
  );
}
