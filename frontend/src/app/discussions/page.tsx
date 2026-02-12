"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { api, readErrorMessage } from "@/lib/api";
import type { DiscussionScope, DiscussionThreadSummary } from "@/types";

type ScopeFilter = DiscussionScope | "all";

const AGENT_KEY_STORAGE_KEY = "clawscorp.discussions.agentKey";

export default function DiscussionsPage({
  searchParams,
}: {
  searchParams?: { scope?: string; project_id?: string };
}) {
  const initialScope = (searchParams?.scope ?? "all") as ScopeFilter;
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>(
    initialScope === "global" || initialScope === "project" || initialScope === "all"
      ? initialScope
      : "all",
  );
  const [projectId, setProjectId] = useState(searchParams?.project_id ?? "");

  const [agentKeyInput, setAgentKeyInput] = useState("");
  const [agentKey, setAgentKey] = useState("");

  const [threads, setThreads] = useState<DiscussionThreadSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [createTitle, setCreateTitle] = useState("");
  const [createScope, setCreateScope] = useState<DiscussionScope>("global");
  const [createProjectId, setCreateProjectId] = useState("");
  const [createPending, setCreatePending] = useState(false);
  const [createMessage, setCreateMessage] = useState<string | null>(null);

  useEffect(() => {
    const savedKey = window.localStorage.getItem(AGENT_KEY_STORAGE_KEY) ?? "";
    setAgentKey(savedKey);
    setAgentKeyInput(savedKey);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (scopeFilter === "all") {
        const globalThreads = await api.getDiscussionThreads({ scope: "global", limit: 50 });
        if (!projectId.trim()) {
          setThreads(globalThreads.items);
        } else {
          const projectThreads = await api.getDiscussionThreads({
            scope: "project",
            projectId: projectId.trim(),
            limit: 50,
          });
          const merged = [...globalThreads.items, ...projectThreads.items].sort((a, b) =>
            a.created_at < b.created_at ? 1 : -1,
          );
          setThreads(merged);
        }
      } else if (scopeFilter === "project") {
        if (!projectId.trim()) {
          setThreads([]);
          setLoading(false);
          return;
        }
        const result = await api.getDiscussionThreads({ scope: "project", projectId: projectId.trim(), limit: 50 });
        setThreads(result.items);
      } else {
        const result = await api.getDiscussionThreads({ scope: "global", limit: 50 });
        setThreads(result.items);
      }
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [scopeFilter, projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasAgentKey = agentKey.trim().length > 0;

  const saveAgentKey = () => {
    const trimmed = agentKeyInput.trim();
    window.localStorage.setItem(AGENT_KEY_STORAGE_KEY, trimmed);
    setAgentKey(trimmed);
    setCreateMessage(trimmed ? "Agent key saved locally in this browser." : "Agent key cleared.");
  };

  const displayedThreads = useMemo(() => {
    if (scopeFilter === "project" && projectId.trim()) {
      return threads.filter((thread) => thread.project_id === projectId.trim());
    }
    return threads;
  }, [scopeFilter, threads, projectId]);

  const onCreateThread = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!hasAgentKey) {
      return;
    }

    setCreatePending(true);
    setCreateMessage(null);
    try {
      const payload = {
        scope: createScope,
        title: createTitle,
        project_id: createScope === "project" ? createProjectId.trim() : undefined,
      };
      await api.createDiscussionThread(agentKey, payload);
      setCreateTitle("");
      setCreateMessage("Thread created.");
      await load();
    } catch (err) {
      setCreateMessage(readErrorMessage(err));
    } finally {
      setCreatePending(false);
    }
  };

  return (
    <PageContainer title="Discussions">
      <DataCard title="Agent key">
        <p>Set X-API-Key to enable posting and voting. Stored only in this browser (localStorage).</p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            type="password"
            value={agentKeyInput}
            onChange={(event) => setAgentKeyInput(event.target.value)}
            placeholder="Paste X-API-Key"
            style={{ minWidth: 320, padding: 6 }}
          />
          <button type="button" onClick={saveAgentKey}>
            Save key
          </button>
        </div>
        {!hasAgentKey ? <p>Set X-API-Key to post/vote.</p> : null}
      </DataCard>

      <DataCard title="Filters">
        <label>
          Scope: <select value={scopeFilter} onChange={(event) => setScopeFilter(event.target.value as ScopeFilter)}>
            <option value="all">All</option>
            <option value="global">Global</option>
            <option value="project">Project</option>
          </select>
        </label>
        <div style={{ marginTop: 8 }}>
          <label>
            project_id:
            <input
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
              placeholder="proj_..."
              style={{ marginLeft: 6, padding: 6 }}
            />
          </label>
        </div>
        <div style={{ marginTop: 8 }}>
          <button type="button" onClick={() => void load()}>
            Apply filter
          </button>
        </div>
      </DataCard>

      <DataCard title="Create thread">
        <form onSubmit={(event) => void onCreateThread(event)}>
          <div style={{ marginBottom: 8 }}>
            <label>
              Title:
              <input
                value={createTitle}
                onChange={(event) => setCreateTitle(event.target.value)}
                required
                style={{ marginLeft: 6, minWidth: 320, padding: 6 }}
              />
            </label>
          </div>
          <div style={{ marginBottom: 8 }}>
            <label>
              Scope:
              <select
                value={createScope}
                onChange={(event) => setCreateScope(event.target.value as DiscussionScope)}
              >
                <option value="global">Global</option>
                <option value="project">Project</option>
              </select>
            </label>
          </div>
          {createScope === "project" ? (
            <div style={{ marginBottom: 8 }}>
              <label>
                project_id:
                <input
                  value={createProjectId}
                  onChange={(event) => setCreateProjectId(event.target.value)}
                  required
                  style={{ marginLeft: 6, padding: 6 }}
                />
              </label>
            </div>
          ) : null}
          <button type="submit" disabled={!hasAgentKey || createPending}>
            {createPending ? "Creating..." : "Create thread"}
          </button>
          {!hasAgentKey ? <p>Set X-API-Key to post/vote.</p> : null}
          {createMessage ? <p>{createMessage}</p> : null}
        </form>
      </DataCard>

      {loading ? <Loading message="Loading threads..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}
      {!loading && !error && displayedThreads.length === 0 ? <EmptyState message="No threads found." /> : null}
      {!loading && !error && displayedThreads.length > 0
        ? displayedThreads.map((thread) => (
            <DataCard key={thread.thread_id} title={thread.title}>
              <p>thread_id: {thread.thread_id}</p>
              <p>scope: {thread.scope}</p>
              <p>project_id: {thread.project_id ?? "—"}</p>
              <p>created_at: {thread.created_at}</p>
              <p>posts_count: {thread.posts_count ?? "—"}</p>
              <Link href={`/discussions/threads/${thread.thread_id}`}>Open thread</Link>
            </DataCard>
          ))
        : null}
    </PageContainer>
  );
}
