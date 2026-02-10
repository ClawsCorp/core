"use client";

interface StateProps {
  message: string;
}

export function Loading({ message }: StateProps) {
  return <p style={{ padding: "12px 0" }}>{message}</p>;
}

export function EmptyState({ message }: StateProps) {
  return <p style={{ padding: "12px 0" }}>{message}</p>;
}
