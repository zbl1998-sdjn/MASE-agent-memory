import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { DataTable } from "../components/DataTable";
import { StatusLine } from "../components/StatusLine";
import type { JsonRecord, Scope } from "../types";

type FactsPageProps = {
  scope: Scope;
  categories: string[];
  readOnly: boolean;
};

const DEFAULT_CATEGORIES = [
  "user_preferences",
  "people_relations",
  "project_status",
  "finance_budget",
  "location_events",
  "general_facts"
];

export function FactsPage({ scope, categories, readOnly }: FactsPageProps) {
  const categoryOptions = categories.length ? categories : DEFAULT_CATEGORIES;
  const [selectedCategory, setSelectedCategory] = useState("");
  const [selectedFact, setSelectedFact] = useState<JsonRecord>();
  const [facts, setFacts] = useState<JsonRecord[]>([]);
  const [history, setHistory] = useState<JsonRecord[]>([]);
  const [form, setForm] = useState({ category: categoryOptions[0], key: "", value: "", reason: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function loadFacts(category = selectedCategory) {
    setLoading(true);
    setError("");
    try {
      const response = await api.facts(scope, category || undefined);
      setFacts(response.data);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadFacts();
  }, [scope, selectedCategory]);

  async function saveFact(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly) {
      setMessage("只读模式：事实写入已禁用");
      return;
    }
    setLoading(true);
    setMessage("");
    setError("");
    try {
      await api.upsertFact(
        { category: form.category, key: form.key, value: form.value, reason: form.reason || undefined },
        scope
      );
      setMessage("事实已写入");
      setForm({ ...form, key: "", value: "", reason: "" });
      await loadFacts();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function showHistory(row: JsonRecord) {
    setSelectedFact(row);
    const category = String(row.category ?? "");
    const key = String(row.entity_key ?? "");
    if (!category || !key) {
      return;
    }
    const response = await api.factHistory(scope, category, key);
    setHistory(response.data);
  }

  async function archiveSelected(row: JsonRecord) {
    if (readOnly) {
      setMessage("只读模式：事实归档已禁用");
      return;
    }
    const category = String(row.category ?? "");
    const key = String(row.entity_key ?? "");
    if (!category || !key) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      await api.forgetFact(category, key, scope);
      setMessage(`已归档 ${category}.${key}`);
      await loadFacts();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid two">
      <Card title="事实写入 / 更新" subtitle="Entity Fact Sheet 当前态">
        <form className="stack-form" onSubmit={saveFact}>
          <label>
            Category
            <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>
              {categoryOptions.map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </label>
          <label>
            Key
            <input value={form.key} onChange={(event) => setForm({ ...form, key: event.target.value })} required />
          </label>
          <label>
            Value
            <textarea value={form.value} onChange={(event) => setForm({ ...form, value: event.target.value })} required />
          </label>
          <label>
            Reason
            <input value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} />
          </label>
          <button type="submit" disabled={readOnly}>保存事实</button>
        </form>
        <StatusLine loading={loading} error={error} message={message} />
      </Card>
      <Card title="事实列表" subtitle="点击行查看历史；双击行归档">
        <div className="toolbar">
          <select value={selectedCategory} onChange={(event) => setSelectedCategory(event.target.value)}>
            <option value="">全部分类</option>
            {categoryOptions.map((item) => (
              <option key={item}>{item}</option>
            ))}
          </select>
          <button type="button" className="secondary" onClick={() => loadFacts()}>
            刷新
          </button>
        </div>
        <DataTable
          rows={facts}
          preferredColumns={["category", "entity_key", "entity_value", "source_reason", "updated_at"]}
          onSelect={showHistory}
        />
        {selectedFact && (
          <button type="button" className="danger" disabled={readOnly} onClick={() => archiveSelected(selectedFact)}>
            归档选中事实
          </button>
        )}
      </Card>
      <Card title="事实历史" subtitle="保留旧值、来源与更新时间">
        <DataTable rows={history} preferredColumns={["category", "entity_key", "old_value", "new_value", "changed_at"]} />
      </Card>
    </div>
  );
}
