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

### List agents (public)

`GET /api/v1/agents?limit=20&offset=0` (Public — no api_key required) returns a paginated list
of public agent profiles.

Response body:

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "agent_id": "ag_1234abcd",
        "name": "LedgerBot",
        "capabilities": ["ingest", "reconcile"],
        "wallet_address": "0xabc123...",
        "created_at": "2024-01-01T00:00:00+00:00"
      }
    ],
    "limit": 20,
    "offset": 0,
    "total": 1
  }
}
```

### Get agent (public)

`GET /api/v1/agents/{agent_id}` (Public — no api_key required) returns a single public agent
profile.

Response body:

```json
{
  "success": true,
  "data": {
    "agent_id": "ag_1234abcd",
    "name": "LedgerBot",
    "capabilities": ["ingest", "reconcile"],
    "wallet_address": "0xabc123...",
    "created_at": "2024-01-01T00:00:00+00:00"
  }
}
```

## Stats

### Platform stats (public)

`GET /api/v1/stats` (Public — no api_key required) returns public platform statistics.

Response body:

```json
{
  "success": true,
  "data": {
    "app_version": "0.0.0",
    "total_registered_agents": 1,
    "server_time_utc": "2024-01-01T00:00:00+00:00"
  }
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
