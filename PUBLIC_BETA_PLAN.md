# Public Beta Plan

## 1. Ideal User Journey

### Target Flow

Google  
↓  
Landing page  
↓  
Download  
↓  
Install  
↓  
Dashboard  
↓  
Connect AI tools  
↓  
First FixOnce opener  
↓  
First success moment

### What the user should feel at each step

#### Google

- “This solves a problem I already have.”
- The promise must be immediate:
  - my AI remembers
  - my sessions continue
  - I stop repeating setup and debugging

#### Landing page

- “I understand what this does in under 10 seconds.”
- Must answer:
  - what is FixOnce
  - who is it for
  - what changes after install
  - why it is safe

#### Download

- “This is easy and trustworthy.”
- One primary CTA
- No decision overload

#### Install

- “The product is taking care of setup.”
- User should not think about Python, ports, MCP, config files, hooks, transport, or runtime

#### Dashboard

- “FixOnce is alive.”
- Dashboard is proof of life, not a control panel first

#### Connect AI tools

- “I can see which apps are ready and what is left.”
- Visibility removes the feeling of silent failure

#### First FixOnce opener

- “It actually knows where I am and what I was doing.”
- This is the first emotional proof that FixOnce is not generic tooling

#### First success moment

- “This already saved me time.”
- Not abstract value
- Specific value within the first session

## 2. First-Time User Friction Map

### 1. Landing page confusion

- Pain:
  - user does not understand whether this is for developers, AI power users, or browser users
- Likelihood:
  - High
- Mitigation:
  - simplify message to one sentence
  - show one concrete before/after example
  - reduce technical vocabulary

### 2. Download hesitation

- Pain:
  - user hesitates to download a desktop installer from an unfamiliar product
- Likelihood:
  - High
- Mitigation:
  - show trust signals
  - show exact OS support
  - explain what is installed locally

### 3. Installer permissions

- Pain:
  - macOS warnings, LaunchAgent concerns, file access prompts
- Likelihood:
  - Medium to High
- Mitigation:
  - explain in plain language why background start exists
  - keep permissions minimal
  - provide visible recovery steps in dashboard, not terminal

### 4. Installer feels finished but AI apps are not ready

- Pain:
  - user thinks install failed because dashboard works but AI app connection is partial
- Likelihood:
  - High
- Mitigation:
  - split “FixOnce installed” from “AI apps connected”
  - surface per-client status in first-run dashboard

### 5. AI app missing

- Pain:
  - user expected Claude/Cursor/Codex/Windsurf support but one app is not installed
- Likelihood:
  - High
- Mitigation:
  - show `Not installed` as informational, not as failure
  - let user continue without guilt

### 6. Restart needed

- Pain:
  - user connected an app but nothing happens until restart
- Likelihood:
  - High
- Mitigation:
  - explicit `Needs restart` status
  - tell user exactly what to do
  - avoid pretending the app is connected if it is not active yet

### 7. Extension confusion

- Pain:
  - browser extension may feel like required setup even when it is optional for the first value moment
- Likelihood:
  - Medium
- Mitigation:
  - do not front-load extension setup in first-run path
  - introduce it after core AI memory is working

### 8. Project detection failure

- Pain:
  - user opens from a folder that does not look like a valid project and sees rejection
- Likelihood:
  - Medium
- Mitigation:
  - clearer error language
  - suggest what counts as a project folder
  - offer quick examples

### 9. Home folder rejection

- Pain:
  - user opens the AI in home directory and FixOnce refuses to init
- Likelihood:
  - Medium
- Mitigation:
  - explain why this is blocked
  - offer one-line guidance: open your actual project folder

### 10. First opener is underwhelming

- Pain:
  - user installs FixOnce but the first opener feels generic or empty
- Likelihood:
  - Medium
- Mitigation:
  - ensure first opener contains project grounding, last work, next step, or visible context
  - optimize for emotional confidence, not just correctness

### 11. No immediate payoff

- Pain:
  - user sees setup complete but does not experience saved effort quickly
- Likelihood:
  - High
- Mitigation:
  - design the first session toward a fast win
  - ideally show continuity, recall, or known-fix reuse in under 60 seconds

### 12. Trust gap

- Pain:
  - user worries FixOnce is too invasive, too opaque, or too fragile
- Likelihood:
  - High
- Mitigation:
  - clear local-first explanation
  - visible state in dashboard
  - honest failure states
  - simple uninstall path

## 3. First “Wow Moment”

### What the user should feel in the first 60 seconds

- “It remembered for me.”
- “It resumed exactly where I left off.”
- “It already prevented wasted time.”

### Candidate wow moments

#### Memory continuity

- Strong because it is the core product promise
- User immediately understands value

#### Error auto-fix

- Very strong when it happens
- Too conditional for a reliable first-time wow

#### Resume

- Strong and emotionally satisfying
- Works best when the user has already had at least one previous session

#### Decision memory

- Valuable, but slower to feel
- Better as retention value than first wow

#### Browser error detection

- Strong for web users
- Too specific to be the universal first wow

### Best first-wow sequence

1. Install succeeds and dashboard opens
2. User sees AI app status clearly
3. User opens their AI in a real project
4. First meaningful message triggers one FixOnce opener
5. Opener shows grounded context:
   - project name
   - last goal or last change
   - next step
6. User immediately continues real work instead of re-explaining context

### Chosen first wow

The best universal wow moment for public beta is:

`Immediate continuity in the first opener`

Why:

- it is reliable
- it is central to the product promise
- it does not depend on a browser extension or a specific bug
- it makes the product feel intelligent, personal, and useful immediately

## 4. Public Beta Scope

### Mandatory

- Mac installer works reliably
- Windows installer path is usable and documented
- Dashboard opens after install
- Per-client connection visibility in dashboard
- Claude, Cursor, Codex, Windsurf onboarding status visible
- Auto-init works for at least the primary supported clients
- One clean first-run onboarding flow
- Clear home-folder rejection message
- Valid memory persistence across sessions
- Basic uninstall / recovery path

### Optional

- Browser extension onboarding in first week
- Per-client retry inside dashboard
- More polished first-run animations and visuals
- Better project examples / demo repo
- Guided sample “try this now” step

### Post-beta

- Rich analytics dashboard
- Advanced onboarding personalization by client
- Team/shared memory flows
- Distribution polish
  - code signing
  - notarization improvements
  - auto-update
- deeper browser and auto-fix loops

## 5. Onboarding Metrics

### Activation funnel

- Landing page visit
- Download started
- Install started
- Install success
- Dashboard opened
- AI app connection written
- AI app connected
- First init
- First saved memory
- First resumed session
- First auto-fix

### Core metrics

#### Install success

- Definition:
  - installer completes and core FixOnce service is alive

#### Dashboard opened

- Definition:
  - dashboard opens at least once after install

#### AI connected

- Definition:
  - at least one supported AI client is configured and recognized as connected or restart-ready

#### First init

- Definition:
  - first successful `fo_init`

#### First saved memory

- Definition:
  - first meaningful write:
    - sync
    - decision
    - solved issue
    - live record update

#### First auto-fix

- Definition:
  - first known fix reused automatically or near-automatically

### Product health metrics

- time from install success to first init
- time from first init to first saved memory
- percentage of users with at least one AI app connected
- percentage of users who return for a second session
- percentage of users who hit home-folder rejection before first success

## 6. Release Checklist

### Mac

- installer works on clean user
- LaunchAgent works
- dashboard opens
- uninstall path tested

### Windows

- install path tested
- startup works
- dashboard opens
- user config paths verified

### Landing

- clear value proposition
- one primary CTA
- trust / local-first explanation
- support matrix visible

### Installer

- success means service is alive
- no silent AI app failures hidden as full install failure
- logs are recoverable

### Dashboard

- first-run app connection screen
- clear client statuses
- no technical wording

### MCP / AI Integration

- Claude config
- Cursor config
- Codex config
- Windsurf config
- rule files or startup instructions written correctly

### Docs

- install docs
- troubleshooting docs
- uninstall docs
- “what to do first” guide

### QA

- fresh user
- fresh machine or VM
- fresh project
- second session continuity
- rejection cases
  - home folder
  - missing AI app
  - restart needed

## 7. Risks Before Public Release

### Technical

- installers behave differently across machines
- AI client config formats change
- runtime/config state can drift
- client detection logic is partly heuristic

### UX

- onboarding still feels too technical
- users may not understand install success vs app connection status
- restart requirements may feel like failure

### Product

- value proposition may be clear to power users but not general developers
- first wow may be delayed if the opener is weak or the user starts in the wrong folder

### Trust

- background service may feel suspicious without explanation
- users may worry about privacy and persistence
- any silent failure reduces confidence fast

### Distribution

- installer trust, signing, and OS warnings can reduce conversion
- public beta support load may spike if onboarding is even slightly ambiguous

## Final Product Principle

For public beta, the product must feel like this:

`FixOnce installs quietly, shows its state honestly, and proves value fast.`

Not:

`FixOnce mostly works if the user is technical enough to diagnose the gaps.`
