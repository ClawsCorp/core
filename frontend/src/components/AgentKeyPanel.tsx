"use client";

import { useEffect, useState } from "react";

import { clearAgentApiKey, getAgentApiKey, setAgentApiKey } from "@/lib/agentKey";

export function AgentKeyPanel() {
  const [value, setValue] = useState("");
  const [status, setStatus] = useState<"missing" | "set">("missing");

  useEffect(() => {
    const saved = getAgentApiKey();
    setValue(saved);
    setStatus(saved ? "set" : "missing");
  }, []);

  const onSave = () => {
    const saved = setAgentApiKey(value);
    setValue(saved);
    setStatus(saved ? "set" : "missing");
  };

  const onClear = () => {
    clearAgentApiKey();
    setValue("");
    setStatus("missing");
  };

  return (
    <section style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 12 }}>
      <h2 style={{ marginTop: 0 }}>Agent key</h2>
      <p>Needed only for agent-write actions. Stored in localStorage in this browser only.</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Paste X-API-Key"
          style={{ minWidth: 320, padding: 6 }}
        />
        <button type="button" onClick={onSave}>
          Save
        </button>
        <button type="button" onClick={onClear}>
          Clear
        </button>
      </div>
      <p>Status: {status === "set" ? "Key set" : "Key missing"}</p>
    </section>
  );
}
