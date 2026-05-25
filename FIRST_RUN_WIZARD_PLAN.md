# First-Run Wizard Plan

## Goal

Keep the install flow simple:

Install  
↓  
Dashboard opens  
↓  
Connect your AI tools

Core setup is considered successful once the local FixOnce service is alive and the dashboard opens.
Connecting AI apps is visible and recoverable in the dashboard instead of being hidden inside installer output.

## First-Run Screen

Title:
`Connect your AI tools`

Supporting copy:
`FixOnce is ready. Finish connecting the apps you use.`

## Cards

One card per supported app:

- Claude
- Cursor
- Codex
- Windsurf

Each card shows:

- App name
- Status
- Short reason in user language
- Primary action if available

## States

### Connected

Meaning:
- App integration files exist
- FixOnce can see the app is configured

User copy:
- `Connected`

### Needs restart

Meaning:
- Integration files were written successfully
- The app likely needs to restart to pick them up

User copy:
- `Needs restart`
- `Close and reopen this app to finish connecting it.`

### Not installed

Meaning:
- The app is not present on this machine

User copy:
- `Not installed`
- `Install this app first if you want to use FixOnce with it.`

### Failed

Meaning:
- FixOnce expected to connect the app but the generated config or rules are missing or invalid

User copy:
- `Could not connect`
- `FixOnce could not finish this app connection yet.`

### Retry

Meaning:
- A safe retry action is available for this specific app

User copy:
- Button: `Retry`

## UX Rules

- User language only
- No mention of MCP, runtime, ports, transport, hooks, or internal tool names
- Core install success must not be downgraded because one app failed to connect
- Missing app is informational, not an install error
- Retry must be per app, not all-or-nothing

## Data Needed Per Card

- `client`
- `status`
- `reason`
- `installed`
- `needs_restart`
- `retry_available`

## Success Criteria

- User sees clearly which apps are ready
- User understands what action is needed, if any
- No hidden onboarding failures
- Dashboard becomes the visible place for app connection state
