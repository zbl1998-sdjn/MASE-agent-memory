import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { DataTable } from "../components/DataTable";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { JsonRecord, Scope } from "../types";

type RecallPageProps = {
  scope: Scope;
};

export function RecallPage({ scope }: RecallPageProps) {
  const [query, setQuery] = useState("budget");
  const [topK, setTopK] = useState(5);
  const [includeHistory, setIncludeHistory] = useState(true);
  const [recallRows, setRecallRows] = useState<JsonRecord[]>([]);
  const [currentRows, setCurrentRows] = useState<JsonRecord[]>([]);
  const [explain, setExplain] = useState<JsonRecord>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const [recall, current, explanation] = await Promise.all([
        api.recall(query, topK, includeHistory, scope),
        api.currentState(query, topK, scope),
        api.explain(query, topK, scope)
      ]);
      setRecallRows(recall.data);
      setCurrentRows(current.data);
      setExplain(explanation.data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="召回查询" subtitle="Facts-first recall、当前事实和 explain 联动">
        <form className="toolbar" onSubmit={search}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="关键词或完整问题" />
          <label>
            Top K
            <input type="number" min="1" max="50" value={topK} onChange={(event) => setTopK(Number(event.target.value))} />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={includeHistory}
              onChange={(event) => setIncludeHistory(event.target.checked)}
            />
            包含历史
          </label>
          <button type="submit">检索</button>
        </form>
        <StatusLine loading={loading} error={error} />
      </Card>
      <div className="grid two">
        <Card title="统一召回结果">
          <DataTable rows={recallRows} preferredColumns={["_source", "category", "entity_key", "entity_value", "content"]} />
        </Card>
        <Card title="当前事实">
          <DataTable rows={currentRows} preferredColumns={["category", "entity_key", "entity_value", "updated_at"]} />
        </Card>
      </div>
      <Card title="Recall Inspector" subtitle="排序、证据类型、freshness、conflict 与 scope 风险">
        <DataTable
          rows={(explain?.hit_inspections as JsonRecord[] | undefined) ?? []}
          preferredColumns={[
            "rank",
            "source",
            "evidence_type",
            "selected_reason",
            "freshness",
            "conflict_status",
            "risk_flags",
            "scope_mismatches",
            "content_preview"
          ]}
        />
      </Card>
      <Card title="Explain">
        <JsonBlock value={explain ?? {}} filename="mase-explain.json" />
      </Card>
    </div>
  );
}
