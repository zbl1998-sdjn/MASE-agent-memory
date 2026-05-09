import type { Scope } from "../types";

type ScopeBarProps = {
  scope: Scope;
  onChange: (scope: Scope) => void;
};

export function ScopeBar({ scope, onChange }: ScopeBarProps) {
  return (
    <div className="scope-bar">
      <label>
        Tenant
        <input
          value={scope.tenant_id ?? ""}
          placeholder="默认全局"
          onChange={(event) => onChange({ ...scope, tenant_id: event.target.value })}
        />
      </label>
      <label>
        Workspace
        <input
          value={scope.workspace_id ?? ""}
          placeholder="默认工作区"
          onChange={(event) => onChange({ ...scope, workspace_id: event.target.value })}
        />
      </label>
      <label>
        Visibility
        <select
          value={scope.visibility ?? ""}
          onChange={(event) => onChange({ ...scope, visibility: event.target.value })}
        >
          <option value="">不筛选</option>
          <option value="private">private</option>
          <option value="shared">shared</option>
          <option value="public">public</option>
        </select>
      </label>
    </div>
  );
}
