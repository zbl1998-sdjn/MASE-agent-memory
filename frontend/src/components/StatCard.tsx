type StatCardProps = {
  label: string;
  value: number | string;
  hint?: string;
  tone?: "cyan" | "violet" | "green" | "amber";
};

export function StatCard({ label, value, hint, tone = "cyan" }: StatCardProps) {
  return (
    <div className={`stat-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  );
}
