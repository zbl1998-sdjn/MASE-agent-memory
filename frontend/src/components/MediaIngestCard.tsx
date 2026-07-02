import type { MediaUploadData } from "../types";

// 卡片展示逻辑抽成纯函数:仓库测试基建是无 DOM 的纯函数风格,
// 渲染层保持薄,摘要逻辑可被 vitest 直接钉住。
export function summarizeMediaUpload(data: MediaUploadData): {
  shaPrefix: string;
  model: string;
  factLines: string[];
  warnings: string[];
  dedupLabel: string;
} {
  return {
    shaPrefix: data.sha256.slice(0, 12),
    model: data.extraction.model,
    factLines: data.extraction.facts.map(
      (fact) => `${fact.category}.${fact.key} = ${fact.value}`
    ),
    warnings: data.extraction.warnings,
    dedupLabel: data.deduplicated ? "已入库(内容相同,未重复抽取)" : ""
  };
}

type MediaIngestCardProps = {
  fileName: string;
  data?: MediaUploadData;
  error?: string;
};

export function MediaIngestCard({ fileName, data, error }: MediaIngestCardProps) {
  if (error) {
    return (
      <div className="bubble assistant media-card">
        <strong>📎 {fileName}</strong>
        <p className="warning">上传失败: {error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="bubble assistant media-card">
        <strong>📎 {fileName}</strong>
        <p>正在抽取…</p>
      </div>
    );
  }
  const summary = summarizeMediaUpload(data);
  return (
    <div className="bubble assistant media-card">
      <strong>
        📎 {fileName} <span className="muted">sha256:{summary.shaPrefix} · {summary.model}</span>
      </strong>
      {summary.dedupLabel ? <p className="muted">{summary.dedupLabel}</p> : null}
      {summary.factLines.length > 0 ? (
        <ul>
          {summary.factLines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">未抽取到结构化事实(全文已入库可召回)。</p>
      )}
      <details>
        <summary>抽取全文摘录</summary>
        <p>{data.extraction.full_text_excerpt}</p>
      </details>
      {summary.warnings.length > 0 ? (
        <p className="warning">{summary.warnings.join("; ")}</p>
      ) : null}
    </div>
  );
}
