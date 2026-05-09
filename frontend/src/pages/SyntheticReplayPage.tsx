import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { MaseResponse, Scope, SyntheticReplayData } from "../types";

type SyntheticReplayPageProps = {
  scope: Scope;
};

const defaultCases = JSON.stringify(
  [
    {
      case_id: "project-owner",
      query: "project owner",
      expected_terms: ["Alice"],
      forbidden_terms: ["Bob"]
    }
  ],
  null,
  2
);

export function SyntheticReplayPage({ scope }: SyntheticReplayPageProps) {
  const [casesJson, setCasesJson] = useState(defaultCases);
  const [report, setReport] = useState<MaseResponse<SyntheticReplayData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runReplay(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const cases = JSON.parse(casesJson) as unknown;
      if (!Array.isArray(cases)) {
        throw new Error("Cases JSON must be an array");
      }
      setReport(await api.syntheticReplay({ cases }, scope));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Synthetic Memory Replay" subtitle="只读回放 curated query，检测漏召回和禁用旧值">
        <form className="stack-form" onSubmit={runReplay}>
          <label>
            Replay cases JSON
            <textarea rows={12} value={casesJson} onChange={(event) => setCasesJson(event.target.value)} />
          </label>
          <button type="submit">运行合成回放</button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <div className="grid cards-3">
            <Card title="Cases">{report.data.summary.case_count ?? 0}</Card>
            <Card title="Passed">{report.data.summary.passed_count ?? 0}</Card>
            <Card title="Failed">{report.data.summary.failed_count ?? 0}</Card>
          </div>
          <Card title="Replay results">
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Status</th>
                    <th>Hits</th>
                    <th>Missing expected</th>
                    <th>Found forbidden</th>
                  </tr>
                </thead>
                <tbody>
                  {report.data.results.map((result, index) => (
                    <tr key={index}>
                      <td>{String(result.case_id ?? "")}</td>
                      <td>{String(result.status ?? "")}</td>
                      <td>{String(result.hit_count ?? 0)}</td>
                      <td>{String((result.missing_expected_terms as string[] | undefined)?.join(", ") ?? "")}</td>
                      <td>{String((result.found_forbidden_terms as string[] | undefined)?.join(", ") ?? "")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Replay payload">
            <JsonBlock value={report} filename="mase-synthetic-replay.json" />
          </Card>
        </>
      )}
    </div>
  );
}
