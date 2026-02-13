"use client";

import { useCallback, useState } from "react";

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [feedback, setFeedback] = useState<string | null>(null);

  const onCopy = useCallback(async () => {
    if (!navigator.clipboard?.writeText) {
      setFeedback("Clipboard unavailable");
      return;
    }

    try {
      await navigator.clipboard.writeText(value);
      setFeedback("Copied");
      window.setTimeout(() => setFeedback(null), 1500);
    } catch {
      setFeedback("Copy failed");
    }
  }, [value]);

  return (
    <>
      <button type="button" onClick={() => void onCopy()}>
        {label}
      </button>
      {feedback ? <span> ({feedback})</span> : null}
    </>
  );
}
