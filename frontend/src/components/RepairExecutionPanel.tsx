import { useState } from "react";
import { api } from "../api";
import { JsonBlock } from "./JsonBlock";
import type { JsonValue, MaseResponse, RepairCase, RepairCaseExecutionData } from "../types";

type RepairExecutionPanelProps = {
  caseItem: RepairCase;
  onExecuted: () => Promise<void>;
  onError: (message: string) => void;
};

const DEFAULT_OPERATION = `[
  {
    "operation": "upsert_fact",
    "category": "project",
    "entity_key": "owner",
    "entity_value": "alice",
    "reason": "repair_execution"
  }
]`;

function parseOperations(value: string): Array<{ [key: string]: JsonValue }> {
  const parsed = JSON.parse(value) as unknown;
  if (!Array.isArray(parsed) || parsed.some((item) => !item || typeof item !== "object" || Array.isArray(item))) {
    throw new Error("Execution operations must be an array of objects");
  }
  return parsed as Array<{ [key: string]: JsonValue }>;
}

export function RepairExecutionPanel({ caseItem, onExecuted, onError }: RepairExecutionPanelProps) {
  const [operationsJson, setOperationsJson] = useState(DEFAULT_OPERATION);
  const [validationQuery, setValidationQuery] = useState("");
  const [result, setResult] = useState<MaseResponse<RepairCaseExecutionData>>();

  async function execute() {
    try {
      const operations = parseOperations(operationsJson);
      const response = await api.executeRepairCase(caseItem.case_id, {
        confirm: true,
        operations,
        validation_query: validationQuery
      });
      setResult(response);
      await onExecuted();
    } catch (err) {
      onError((err as Error).message);
    }
  }

  if (caseItem.status !== "approved") {
    return null;
  }

  return (
    <details>
      <summary>approved execution</summary>
      <div className="stack">
        <label>
          Operations JSON
          <textarea value={operationsJson} onChange={(event) => setOperationsJson(event.target.value)} />
        </label>
        <label>
          Validation query
          <input value={validationQuery} onChange={(event) => setValidationQuery(event.target.value)} />
        </label>
        <button type="button" onClick={() => void execute()}>
          execute approved repair
        </button>
        {result && <JsonBlock value={result} filename={`${caseItem.case_id}-execution.json`} />}
      </div>
    </details>
  );
}
