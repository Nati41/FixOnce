# Dashboard Status Contract

## Purpose

Define the per-client onboarding status payload used by the dashboard first-run screen.

## Response Shape

```json
{
  "clients": [
    {
      "client": "claude",
      "status": "connected",
      "reason": "Ready to use",
      "retry_available": false,
      "installed": true,
      "needs_restart": false
    }
  ]
}
```

## Fields

### `client`

- Type: string
- Allowed values:
  - `claude`
  - `cursor`
  - `codex`
  - `windsurf`

### `status`

- Type: string
- Allowed values:
  - `connected`
  - `needs_restart`
  - `not_installed`
  - `failed`

### `reason`

- Type: string
- Human-readable explanation for the current state
- Must use user language only
- Must not expose internal terms like MCP, runtime, port, hook, transport

### `retry_available`

- Type: boolean
- `true` when the dashboard can safely offer a retry action for this client

### `installed`

- Type: boolean
- `true` when the app appears to exist on the machine

### `needs_restart`

- Type: boolean
- `true` when FixOnce wrote the necessary connection files but the app likely needs a restart before the connection is active

## State Rules

### Connected

- `status = "connected"`
- `installed = true`
- `needs_restart = false`

### Needs restart

- `status = "needs_restart"`
- `installed = true`
- `needs_restart = true`

### Not installed

- `status = "not_installed"`
- `installed = false`
- `retry_available = false`

### Failed

- `status = "failed"`
- `installed` may be `true` or `false`
- `retry_available = true` when retrying is safe

## Notes

- Core FixOnce install success is independent from these client states.
- Dashboard should show all supported clients even when they are not installed.
- Missing client is informational, not a product failure.
