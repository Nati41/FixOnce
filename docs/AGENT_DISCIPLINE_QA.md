# Agent Discipline QA

`scripts/agent_discipline_qa.py` is an offline transcript analyzer for the
FixOnce agent-discipline scenarios. It does not call Claude, Codex, FixOnce,
or any network service.

## Run

```bash
python3 scripts/agent_discipline_qa.py --print-markdown
```

Equivalent explicit form:

```bash
python3 scripts/agent_discipline_qa.py \
  --fixtures tests/fixtures/agent_discipline \
  --out /tmp/agent_qa_report
```

Default input:

```text
tests/fixtures/agent_discipline/*.txt
```

Default output:

```text
build/agent_discipline_qa/report.json
build/agent_discipline_qa/report.md
```

Analyze a manually saved transcript:

```bash
python3 scripts/agent_discipline_qa.py /path/to/transcript.txt \
  --json-report /tmp/agent-report.json \
  --markdown-report /tmp/agent-report.md \
  --print-markdown
```

## Transcript Format

The normalized format is intentionally simple:

```text
SCENARIO: project_context_avoid
EXPECTED: PASS

USER: project_context.py feels messy, let's clean it.
TOOL: fo_search
RESULT: AVOID PATTERN
Avoid: Broad cleanup of project_context.py.
Reason: It previously broke project identity resolution.
ASSISTANT: The project_context.py cleanup is risky, so I am stopping here.
```

Supported scenario identifiers:

| Scenario | Purpose |
|---|---|
| `mcp_tools_regression` | A complete 45-to-8 memory decision must stop investigation. |
| `project_context_avoid` | An AVOID PATTERN must be summarized before code access and stop the cleanup. |
| `recurring_fo_sync_timeout` | `fo_search` must happen before code investigation. |
| `continue` | `fo_init` must provide `Last` and `Next` before the agent responds. |

`EXPECTED` is optional. It is useful for fixture tests:

- `EXPECTED: PASS` means the transcript should comply.
- `EXPECTED: FAIL` means the harness should detect a violation.
- Without `EXPECTED`, a detected failure makes the command exit with status 1.

Continuation lines belong to the preceding `USER`, `ASSISTANT`, or `RESULT`
event. The parser also recognizes common pasted forms containing
`assistant to=<tool>` and `<tool_use name="<tool>">`.

## What V1 Detects

The harness reports:

- pass/fail for every transcript;
- every detected tool call;
- failed checks and detected violations;
- JSON details for automation;
- a Markdown summary table for review.

V1 uses deterministic text and ordering rules. It does not claim semantic
understanding. For reliable results, preserve tool names and FixOnce result
labels such as `ACTIVE DECISION`, `AVOID PATTERN`, `Last:`, and `Next:`.

## CLI Automation

Claude or Codex CLI execution can be added later as a separate transcript
producer. It should remain optional because it requires installed CLIs,
credentials, sandbox policy, timeouts, and cost controls. The offline analyzer
should remain the stable acceptance layer for both manually captured and
automatically generated transcripts.
