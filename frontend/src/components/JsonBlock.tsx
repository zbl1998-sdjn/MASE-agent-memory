import { downloadJson } from "../utils";

type JsonBlockProps = {
  value: unknown;
  filename?: string;
};

export function JsonBlock({ value, filename = "mase-export.json" }: JsonBlockProps) {
  return (
    <div className="json-block">
      <button type="button" className="ghost" onClick={() => downloadJson(filename, value)}>
        导出 JSON
      </button>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}
