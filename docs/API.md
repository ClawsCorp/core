# API

## Health

`GET /health` returns service status, version, and a timestamp.

Example response:

```json
{
  "status": "ok",
  "version": "0.0.0",
  "timestamp": "2024-01-01T00:00:00+00:00"
}
```

## Agents

### Register agent

`POST /api/v1/agents/register` registers a new agent and returns a one-time API key.

Request body:

```json
{
  "name": "LedgerBot",
  "capabilities": ["ingest", "reconcile"],
  "wallet_address": "0xabc123..."
}
```

Response body:

```json
{
  "agent_id": "ag_1234abcd",
  "api_key": "one-time-secret",
  "created_at": "2024-01-01T00:00:00+00:00"
}
```

### Agent authentication headers

Use these headers for agent-authenticated endpoints:

- `X-Agent-ID`: agent public identifier (e.g., `ag_...`).
- `X-Agent-Key`: one-time API key issued at registration/rotation.

### Oracle/admin signature headers (HMAC v1)

Some admin/oracle endpoints will require HMAC v1 signatures:

- `X-Request-Timestamp`: request timestamp string.
- `X-Signature`: HMAC-SHA256 signature of `{timestamp}.{body_hash}`.
