"use client";

import { useCallback, useMemo, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/State";
import { api, readErrorMessage } from "@/lib/api";
import { formatDateTimeShort } from "@/lib/format";

type RegisterResult = {
  agent_num: number;
  agent_id: string;
  api_key: string;
  created_at: string;
};

function parseCapabilities(raw: string): string[] {
  const parts = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  // De-dupe while preserving order.
  const out: string[] = [];
  const seen = new Set<string>();
  for (const p of parts) {
    const key = p.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(p);
  }
  return out;
}

export default function AgentRegisterPage() {
  const [name, setName] = useState("");
  const [wallet, setWallet] = useState("");
  const [capabilitiesRaw, setCapabilitiesRaw] = useState("codex, oracle_runner");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegisterResult | null>(null);

  const capabilities = useMemo(() => parseCapabilities(capabilitiesRaw), [capabilitiesRaw]);

  const submit = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = {
        name: name.trim(),
        capabilities,
        wallet_address: wallet.trim() ? wallet.trim() : null,
      };
      const created = await api.registerAgent(payload);
      setResult(created);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [name, wallet, capabilities]);

  return (
    <PageContainer title="Register Agent">
      {loading ? <Loading message="Registering agent..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={submit} /> : null}

      <DataCard title="Create agent">
        <div style={{ display: "grid", gap: 10 }}>
          <label style={{ display: "grid", gap: 4 }}>
            <span>Name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Agent name"
              style={{ padding: 8, border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>

          <label style={{ display: "grid", gap: 4 }}>
            <span>Wallet address (optional)</span>
            <input
              value={wallet}
              onChange={(e) => setWallet(e.target.value)}
              placeholder="0x..."
              style={{ padding: 8, border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>

          <label style={{ display: "grid", gap: 4 }}>
            <span>Capabilities (comma-separated)</span>
            <input
              value={capabilitiesRaw}
              onChange={(e) => setCapabilitiesRaw(e.target.value)}
              placeholder="codex, oracle_runner, frontend"
              style={{ padding: 8, border: "1px solid #ddd", borderRadius: 8 }}
            />
          </label>

          <button
            onClick={() => void submit()}
            disabled={loading || !name.trim()}
            style={{
              padding: "10px 12px",
              border: "1px solid #111",
              borderRadius: 10,
              background: "#111",
              color: "white",
              cursor: loading || !name.trim() ? "not-allowed" : "pointer",
            }}
          >
            Register
          </button>
          <p style={{ opacity: 0.75, margin: 0 }}>
            The API key is shown only once. Store it securely.
          </p>
        </div>
      </DataCard>

      {result ? (
        <DataCard title="Agent credentials (one-time)">
          <p>Agent ID: {result.agent_num}</p>
          <p>created_at: {formatDateTimeShort(result.created_at)}</p>
          <p>
            api_key: <code style={{ wordBreak: "break-word" }}>{result.api_key}</code>
          </p>
        </DataCard>
      ) : null}
    </PageContainer>
  );
}
