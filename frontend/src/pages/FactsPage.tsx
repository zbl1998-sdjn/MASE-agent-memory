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
  const [selectedReview, setSelectedReview] = useState<JsonRecord>();
  const [facts, setFacts] = useState<JsonRecord[]>([]);
  const [reviewQueue, setReviewQueue] = useState<JsonRecord[]>([]);
  const [history, setHistory] = useState<JsonRecord[]>([]);
  const [form, setForm] = useState({ category: categoryOptions[0], key: "", value: "", reason: "" });
  const [editForm, setEditForm] = useState({ object_value: "", evidence_text: "", source_full_text: "", reason: "" });
  const [mergeTarget, setMergeTarget] = useState("");
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

  async function loadReviewQueue() {
    setError("");
    try {
      const response = await api.governanceReviewQueue(scope);
      setReviewQueue(response.data);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  useEffect(() => {
    loadFacts();
    loadReviewQueue();
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

  function firstEvidence(row: JsonRecord): JsonRecord | undefined {
    const evidence = row.evidence;
    if (Array.isArray(evidence) && evidence.length && typeof evidence[0] === "object" && evidence[0] !== null) {
      return evidence[0] as JsonRecord;
    }
    return undefined;
  }

  function selectReview(row: JsonRecord) {
    setSelectedReview(row);
    const evidence = firstEvidence(row);
    const quote = String(evidence?.quote_excerpt ?? row.object ?? "");
    setEditForm({
      object_value: String(row.object ?? ""),
      evidence_text: quote,
      source_full_text: quote,
      reason: ""
    });
    setMergeTarget("");
  }

  async function runReviewAction(action: "approve" | "reject" | "retract", row: JsonRecord) {
    if (readOnly) {
      setMessage("只读模式：治理动作已禁用");
      return;
    }
    const factId = String(row.fact_id ?? "");
    if (!factId) {
      return;
    }
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const body = { reason: `ui:${action}` };
      if (action === "approve") {
        await api.approveGovernanceFact(factId, body, scope);
      } else if (action === "reject") {
        await api.rejectGovernanceFact(factId, body, scope);
      } else {
        await api.retractGovernanceFact(factId, body, scope);
      }
      setMessage(`已执行 ${action}: ${factId}`);
      await loadReviewQueue();
      await loadFacts();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function saveReviewEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly || !selectedReview) {
      setMessage("只读模式：治理修订已禁用");
      return;
    }
    const factId = String(selectedReview.fact_id ?? "");
    if (!factId) {
      return;
    }
    setLoading(true);
    setError("");
    setMessage("");
    try {
      await api.editGovernanceFact(factId, editForm, scope);
      setMessage(`已修订 ${factId}`);
      await loadReviewQueue();
      await loadFacts();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function mergeReviewFact() {
    if (readOnly || !selectedReview || !mergeTarget.trim()) {
      return;
    }
    const factId = String(selectedReview.fact_id ?? "");
    setLoading(true);
    setError("");
    setMessage("");
    try {
      await api.mergeGovernanceFact(factId, { target_fact_id: mergeTarget.trim(), reason: "ui:merge" }, scope);
      setMessage(`已归并 ${factId}`);
      await loadReviewQueue();
      await loadFacts();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  function exportSelectedReview() {
    if (!selectedReview) {
      return;
    }
    const blob = new Blob([JSON.stringify(selectedReview, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${String(selectedReview.fact_id ?? "governance-fact")}.json`;
    link.click();
    URL.revokeObjectURL(url);
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
      <Card title="Review Inbox" subtitle="quarantined facts with evidence and conflicts">
        <div className="toolbar">
          <button type="button" className="secondary" onClick={() => loadReviewQueue()}>
            刷新
          </button>
          {selectedReview && (
            <button type="button" className="secondary" onClick={exportSelectedReview}>
              导出 JSON
            </button>
          )}
        </div>
        <DataTable
          rows={reviewQueue}
          preferredColumns={["fact_id", "subject", "predicate", "object", "sensitivity", "updated_at"]}
          onSelect={selectReview}
        />
        {selectedReview && (
          <div className="stack-form">
            <div className="button-row">
              <button type="button" disabled={readOnly} onClick={() => runReviewAction("approve", selectedReview)}>
                Approve
              </button>
              <button type="button" className="secondary" disabled={readOnly} onClick={() => runReviewAction("reject", selectedReview)}>
                Reject
              </button>
              <button type="button" className="danger" disabled={readOnly} onClick={() => runReviewAction("retract", selectedReview)}>
                Retract
              </button>
            </div>
            <form className="stack-form" onSubmit={saveReviewEdit}>
              <label>
                Object
                <input
                  value={editForm.object_value}
                  onChange={(event) => setEditForm({ ...editForm, object_value: event.target.value })}
                  required
                />
              </label>
              <label>
                Evidence Text
                <textarea
                  value={editForm.evidence_text}
                  onChange={(event) => setEditForm({ ...editForm, evidence_text: event.target.value })}
                  required
                />
              </label>
              <label>
                Source Full Text
                <textarea
                  value={editForm.source_full_text}
                  onChange={(event) => setEditForm({ ...editForm, source_full_text: event.target.value })}
                  required
                />
              </label>
              <label>
                Reason
                <input value={editForm.reason} onChange={(event) => setEditForm({ ...editForm, reason: event.target.value })} />
              </label>
              <button type="submit" disabled={readOnly}>保存修订</button>
            </form>
            <div className="toolbar">
              <label>
                Merge Target
                <input value={mergeTarget} onChange={(event) => setMergeTarget(event.target.value)} />
              </label>
              <button type="button" className="secondary" disabled={readOnly || !mergeTarget.trim()} onClick={mergeReviewFact}>
                Merge
              </button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
