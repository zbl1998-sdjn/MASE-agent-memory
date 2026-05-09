type StatusLineProps = {
  loading?: boolean;
  error?: string;
  message?: string;
};

export function StatusLine({ loading, error, message }: StatusLineProps) {
  if (loading) {
    return <p className="status loading">处理中...</p>;
  }
  if (error) {
    return <p className="status error">{error}</p>;
  }
  if (message) {
    return <p className="status success">{message}</p>;
  }
  return null;
}
