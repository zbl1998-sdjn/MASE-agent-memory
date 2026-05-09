import type { JsonRecord, JsonValue } from "../types";
import { formatValue } from "../utils";

type DataTableProps = {
  rows: JsonRecord[];
  preferredColumns?: string[];
  onSelect?: (row: JsonRecord) => void;
};

function collectColumns(rows: JsonRecord[], preferredColumns: string[]): string[] {
  const seen = new Set<string>();
  const columns: string[] = [];
  for (const key of preferredColumns) {
    if (rows.some((row) => row[key] !== undefined)) {
      columns.push(key);
      seen.add(key);
    }
  }
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!seen.has(key) && columns.length < 8) {
        columns.push(key);
        seen.add(key);
      }
    }
  }
  return columns;
}

export function DataTable({ rows, preferredColumns = [], onSelect }: DataTableProps) {
  if (!rows.length) {
    return <div className="empty">暂无数据</div>;
  }
  const columns = collectColumns(rows, preferredColumns);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${formatValue(row.id as JsonValue)}-${index}`} onClick={() => onSelect?.(row)}>
              {columns.map((column) => (
                <td key={column}>
                  <pre>{formatValue(row[column])}</pre>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
