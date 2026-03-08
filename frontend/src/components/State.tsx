"use client";

import styles from "./Feedback.module.css";

interface StateProps {
  message: string;
}

export function Loading({ message }: StateProps) {
  return (
    <div className={`${styles.box} ${styles.loading}`}>
      <p>{message}</p>
    </div>
  );
}

export function EmptyState({ message }: StateProps) {
  return (
    <div className={`${styles.box} ${styles.empty}`}>
      <p>{message}</p>
    </div>
  );
}
