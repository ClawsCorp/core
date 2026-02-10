"use client";

interface ErrorStateProps {
  message: string;
  onRetry: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div style={{ padding: "12px 0" }}>
      <p>{message}</p>
      <button type="button" onClick={onRetry} style={{ marginTop: 8 }}>
        Retry
      </button>
    </div>
  );
}
