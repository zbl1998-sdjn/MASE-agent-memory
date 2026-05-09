import type { Scope } from "../types";
import { getScopeGuardStatus } from "../utils";

type ScopeGuardProps = {
  scope: Scope;
};

export function ScopeGuard({ scope }: ScopeGuardProps) {
  const status = getScopeGuardStatus(scope);
  return (
    <div className={`scope-guard ${status.level}`}>
      <strong>{status.label}</strong>
      <span>{status.message}</span>
      {status.missingKeys.length > 0 && <small>Missing: {status.missingKeys.join(", ")}</small>}
    </div>
  );
}
