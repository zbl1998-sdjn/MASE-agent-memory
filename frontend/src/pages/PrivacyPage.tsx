import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card } from "../components/Card";
import { JsonBlock } from "../components/JsonBlock";
import { StatusLine } from "../components/StatusLine";
import type { JsonRecord, MaseResponse, PrivacyPreviewData, PrivacyScanData, Scope } from "../types";

type PrivacyPageProps = {
  scope: Scope;
};

function parseJsonObject(value: string): JsonRecord {
  const parsed = value.trim() ? (JSON.parse(value) as unknown) : {};
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Preview payload must be a JSON object");
  }
  return parsed as JsonRecord;
}

export function PrivacyPage({ scope }: PrivacyPageProps) {
  const [scan, setScan] = useState<MaseResponse<PrivacyScanData>>();
  const [preview, setPreview] = useState<MaseResponse<PrivacyPreviewData>>();
  const [payload, setPayload] = useState('{"note":"email alice@example.com","api_key":"sk-secretsecretsecretsecret"}');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runScan() {
    setLoading(true);
    setError("");
    try {
      setScan(await api.privacyScan(scope, 100));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function runPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      setPreview(await api.privacyPreview(parseJsonObject(payload)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="stack">
      <Card title="Privacy & Redaction" subtitle="扫描记忆表面的敏感字段、正文 token、邮箱和密钥形态">
        <div className="button-row">
          <button type="button" onClick={() => void runScan()}>
            扫描当前 scope
          </button>
        </div>
        <StatusLine loading={loading} error={error} />
      </Card>

      {scan && (
        <div className="grid two">
          <Card title="Scan summary">
            <div className="summary-grid">
              <div className="metric-card">
                <span>items</span>
                <strong>{String(scan.data.summary.item_count ?? 0)}</strong>
              </div>
              <div className="metric-card">
                <span>findings</span>
                <strong>{String(scan.data.summary.finding_count ?? 0)}</strong>
              </div>
            </div>
          </Card>
          <Card title="Redaction report">
            <JsonBlock value={scan} filename="mase-privacy-scan.json" />
          </Card>
        </div>
      )}

      <Card title="Redaction preview" subtitle="粘贴 JSON 验证脱敏效果，不会写入记忆">
        <form className="stack-form" onSubmit={runPreview}>
          <textarea value={payload} onChange={(event) => setPayload(event.target.value)} />
          <button type="submit">预览脱敏</button>
        </form>
      </Card>

      {preview && (
        <Card title="Preview result">
          <JsonBlock value={preview} filename="mase-privacy-preview.json" />
        </Card>
      )}
    </div>
  );
}
