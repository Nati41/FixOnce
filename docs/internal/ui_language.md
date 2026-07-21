# FixOnce UI Language

FixOnce should feel like a calm AI teammate, not like a control panel.

This is guidance, not infrastructure.

---

## Stay calm

No excitement, no marketing, no "Welcome back!" on every launch.

Prefer:
```
Claude is connected.
```

Avoid:
```
Welcome back! Everything is awesome!
```

---

## Preserve scanability

Users should understand the state within a few seconds.

Friendly labels are fine.

Avoid:
```
STATUS
MEMORY
CONTEXT
```

Prefer:
```
Connected
Where we stopped
Saved recently
```

---

## Explain only when useful

Normal state should stay quiet.

Only explain when attention is needed.

Example:
```
Two memories are waiting for approval.
No rush — they'll stay here until you're ready.
```

---

## Actions stay short

Buttons should remain simple.

Examples:
```
Save memories
Reconnect
Pause
Settings
```

Avoid conversational buttons.

---

## One idea per sentence

Avoid long paragraphs.

Prefer:
```
Last time we moved to the new layout.

Next, verify everything works correctly.
```

---

## Don't sound technical

Avoid raw developer wording when possible.

Prefer human wording.

---

## Be invisible when nothing needs attention

FixOnce should mostly stay out of the way.

It speaks only when useful.

---

## Don't use "commit" for memories

"Commit" sounds like Git and confuses users.

Avoid:
```
Commit Knowledge
Knowledge Commit
Pending Knowledge
```

Prefer:
```
Save memories
Memories waiting for approval
Saved recently
```

Reserve "commit" only for actual Git/code commits.

---

## Internal rule: when to record memories

Git remembers what changed.
FixOnce remembers what matters.

Record memory only when future agents would:
- Repeat the same mistake
- Miss an important decision
- Waste time rediscovering something

Not every code change needs a memory.
