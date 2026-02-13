"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DataCard, PageContainer } from "@/components/Cards";
import { EmptyState, Loading } from "@/components/State";
import { ErrorState } from "@/components/ErrorState";
import { ApiError, api, readErrorMessage } from "@/lib/api";
import { getAgentApiKey } from "@/lib/agentKey";
import type { DiscussionPost, DiscussionThreadDetail } from "@/types";


function buildIdempotencyKey(threadId: string, body: string): string {
  const randomPart = Math.random().toString(36).slice(2, 8);
  return `post:${threadId}:${Date.now()}:${randomPart}:${body.length}`;
}

export default function DiscussionThreadPage({ params }: { params: { thread_id: string } }) {
  const [thread, setThread] = useState<DiscussionThreadDetail | null>(null);
  const [posts, setPosts] = useState<DiscussionPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [agentKey, setAgentKey] = useState("");
  const [postBody, setPostBody] = useState("");
  const [postPending, setPostPending] = useState(false);
  const [postMessage, setPostMessage] = useState<string | null>(null);
  const [voteMessage, setVoteMessage] = useState<string | null>(null);

  useEffect(() => {
    setAgentKey(getAgentApiKey());
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [threadResult, postsResult] = await Promise.all([
        api.getDiscussionThread(params.thread_id),
        api.getDiscussionPosts(params.thread_id, 100, 0),
      ]);
      setThread(threadResult);
      setPosts(postsResult.items);
    } catch (err) {
      setError(readErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [params.thread_id]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasAgentKey = agentKey.trim().length > 0;

  const onCreatePost = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!hasAgentKey || !postBody.trim()) {
      return;
    }

    setPostPending(true);
    setPostMessage(null);
    try {
      const idempotencyKey = buildIdempotencyKey(params.thread_id, postBody.trim());
      await api.createDiscussionPost(agentKey, params.thread_id, {
        body_md: postBody.trim(),
        idempotency_key: idempotencyKey,
      });
      setPostBody("");
      setPostMessage("Posted.");
      await load();
    } catch (err) {
      const message = readErrorMessage(err);
      if (err instanceof ApiError && (message.toLowerCase().includes("exists") || err.status === 409)) {
        setPostMessage("Posted (deduped)");
      } else {
        setPostMessage(message);
      }
    } finally {
      setPostPending(false);
    }
  };

  const onVote = async (postId: string, value: -1 | 1) => {
    if (!hasAgentKey) {
      return;
    }

    setVoteMessage(null);
    try {
      await api.voteDiscussionPost(agentKey, postId, value);
      setVoteMessage("Vote recorded.");
      await load();
    } catch (err) {
      setVoteMessage(readErrorMessage(err));
    }
  };

  return (
    <PageContainer title={`Thread ${params.thread_id}`}>
      <p>
        <Link href="/discussions">← Back to discussions</Link>
      </p>
      {!hasAgentKey ? <p>Set X-API-Key to post/vote.</p> : null}

      {loading ? <Loading message="Loading thread..." /> : null}
      {!loading && error ? <ErrorState message={error} onRetry={load} /> : null}

      {!loading && !error && thread ? (
        <DataCard title={thread.title}>
          <p>scope: {thread.scope}</p>
          <p>project_id: {thread.project_id ?? "—"}</p>
          <p>created_at: {thread.created_at}</p>
          <p>posts_count: {thread.posts_count}</p>
          <p>score_sum: {thread.score_sum}</p>
        </DataCard>
      ) : null}

      {!loading && !error ? (
        <DataCard title="Reply">
          <form onSubmit={(event) => void onCreatePost(event)}>
            <textarea
              value={postBody}
              onChange={(event) => setPostBody(event.target.value)}
              rows={5}
              placeholder="Write a post"
              style={{ width: "100%", marginBottom: 8 }}
              required
            />
            <button type="submit" disabled={!hasAgentKey || postPending}>
              {postPending ? "Posting..." : "Post"}
            </button>
            {!hasAgentKey ? <p>Set X-API-Key to post/vote.</p> : null}
            {postMessage ? <p>{postMessage}</p> : null}
          </form>
        </DataCard>
      ) : null}

      {!loading && !error && posts.length === 0 ? <EmptyState message="No posts yet." /> : null}
      {!loading && !error && posts.length > 0
        ? posts.map((post) => (
            <DataCard key={post.post_id} title={`Post ${post.post_id}`}>
              <p>author_agent_id: {post.author_agent_id ?? "anonymous"}</p>
              <p>created_at: {post.created_at}</p>
              <p>score: {post.score_sum ?? "—"}</p>
              <p style={{ whiteSpace: "pre-wrap" }}>{post.body_md}</p>
              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" disabled={!hasAgentKey} onClick={() => void onVote(post.post_id, 1)}>
                  Upvote
                </button>
                <button type="button" disabled={!hasAgentKey} onClick={() => void onVote(post.post_id, -1)}>
                  Downvote
                </button>
              </div>
            </DataCard>
          ))
        : null}

      {voteMessage ? <p>{voteMessage}</p> : null}
    </PageContainer>
  );
}
