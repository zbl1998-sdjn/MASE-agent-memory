import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { MaseResponse, RefusalQualityData, Scope } from "../types";

type RefusalQualityPageProps = {
  scope: Scope;
};

export function RefusalQualityPage({ scope }: RefusalQualityPageProps) {
  const [query, setQuery] = useState("Who owns the project?");
  const [answer, setAnswer] = useState("I do not know.");
  const [report, setReport] = useState<MaseResponse<RefusalQualityData>>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function evaluate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      setReport(await api.refusalQuality({ query, answer }, scope));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Refusal Quality" subtitle="区分该拒答、误拒答、无证据硬答">
        <form className="stack-form" onSubmit={evaluate}>
          <label>
            Query
            <input value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <label>
            Answer
            <textarea rows={5} value={answer} onChange={(event) => setAnswer(event.target.value)} />
          </label>
          <button type="submit">评估拒答质量</button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>

      {report && (
        <>
          <div className="grid cards-3">
            <Card title="Classification">{report.data.classification}</Card>
            <Card title="Severity">{report.data.severity}</Card>
            <Card title="Evidence">{report.data.evidence_count}</Card>
          </div>
          <Card title="Recommended actions">
            <ol className="repair-list">
              {report.data.recommended_actions.map((action) => (
                <li key={action}>{action}</li>
              ))}
            </ol>
          </Card>
          <Card title="Refusal payload">
            <JsonBlock value={report} filename="mase-refusal-quality.json" />
          </Card>
        </>
      )}
    </div>
  );
}
