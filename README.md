# Better Drinking Bird

Homer's drinking bird for AI coding agents.

*"King-Size Homer" - The Simpsons, Season 7, Episode 7*

In the famous Simpsons episode, Homer uses a drinking bird toy to repeatedly press a key on his keyboard, keeping his work going while he's away. **Better Drinking Bird** does the same for AI coding agents - it keeps them on task, nudging them back to work when they try to stop prematurely.

## Features

- **Stop Hook** - Blocks premature stops like "Should I proceed?" and nudges agents back to work
- **Safety Guard** - Blocks dangerous commands before execution (`git reset --hard`, `rm -rf /`, etc.)
- **Recovery Hints** - Provides LLM-powered hints when tools fail to help agents recover
- **Context Preservation** - Injects critical files before memory compaction

## Supported Agents

| Agent | Status | Notes |
|-------|--------|-------|
| Claude Code | Full support | Native hooks integration |
| Cursor | Full support | Script-based hooks |
| GitHub Copilot | Full support | Shell command hooks |
| Any (stdin) | Full support | Swiss army knife mode |

## Installation

```bash
# Install with pipx (recommended)
pipx install better-drinking-bird

# Or with pip
pip install better-drinking-bird
```

## Quick Start

```bash
# 1. Install hooks for your agent (creates config automatically)
bdb install claude-code  # or cursor, copilot

# 2. Add your API key to ~/.bdb/config.yaml
# (Edit the file and add your OpenAI/Anthropic key)

# 3. Use your agent as normal - BDB supervises automatically
```

## Configuration

Configuration lives in `~/.bdbrc` (YAML format with 600 permissions for security).

See [config.example.yaml](config.example.yaml) for a complete example with all options.

```yaml
# LLM Provider
llm:
  provider: openai  # openai | anthropic | ollama
  model: gpt-4o-mini
  api_key: sk-your-key-here
  # Or use environment variable:
  # api_key_env: OPENAI_API_KEY

# Agent Configuration
agent:
  type: claude-code
  conversation_depth: 1  # How many exchanges to analyze (0=all)

# Hook Configuration
hooks:
  stop:
    enabled: true
    block_permission_seeking: true  # "Should I proceed?"
    block_plan_deviation: true      # "Let me try simpler..."
    block_quality_shortcuts: true   # "Skip those tests..."

  pre_tool:
    enabled: true
    categories:
      ci_bypass: true        # --no-verify, HUSKY=0
      destructive_git: true  # reset --hard, push --force
      branch_switching: true # checkout main (worktree protection)
      dangerous_files: true  # rm -rf /

  tool_failure:
    enabled: true
    confidence_threshold: medium

  pre_compact:
    enabled: true
    context_patterns:
      - "docs/plans/*.md"
      - "CLAUDE.md"
```

## CLI Commands

```bash
# Install hooks for an agent (creates config automatically)
bdb install claude-code
bdb install cursor
bdb install copilot
bdb install stdin  # Shows usage for generic piping

# Validate configuration
bdb check

# Run in stdin/stdout mode (called by hooks)
bdb run

# Test individual hooks
bdb test stop --transcript ./conversation.jsonl
bdb test pre-tool --command "git reset --hard"
bdb test tool-failure --error "command not found"
bdb test pre-compact

# Configuration management
bdb config show
bdb config template
```

## Swiss Army Knife Mode

Use `bdb run --adapter stdin` with any tool that supports piping:

```bash
# Pipe JSON through BDB
echo '{"event": "pre_tool", "tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}' | bdb run --adapter stdin

# Output:
# {"action": "block", "message": "NO. git reset --hard destroys work. Ask the user first."}
```

Input format:
```json
{
  "event": "stop | pre_tool | tool_failure | pre_compact",
  "tool_name": "...",
  "tool_input": {...},
  "transcript": "..." or [...],
  "cwd": "..."
}
```

Output format:
```json
{
  "action": "allow | block | kill",
  "message": "...",
  "context": "..."
}
```

## How It Works

### Stop Hook

When an agent tries to stop, BDB analyzes the conversation to determine if:

1. **ALLOW** - Task is genuinely complete or requires human input
2. **BLOCK** - Agent stopped prematurely, send it back with encouragement
3. **KILL** - Agent is confused/looping, terminate the process

Common things that get blocked:
- "Should I proceed with this?"
- "Ready for your feedback"
- "This is complex, let me try a simpler approach"
- "We can skip those tests for now"

The agent receives: *"Stick to the plan. Do it right. The reward at the end is worth it."*

### Safety Guard

Blocks dangerous commands before execution:

| Category | Examples |
|----------|----------|
| CI Bypass | `--no-verify`, `HUSKY=0` |
| Destructive Git | `git reset --hard`, `git push --force` |
| Branch Switching | `git checkout main` (corrupts worktrees) |
| Dangerous Files | `rm -rf /`, `cat .env` |

### Recovery Hints

When tools fail, BDB provides LLM-powered hints:

```
[HINT (high)]: Try 'npm install --legacy-peer-deps' to resolve the dependency conflict. Keep going!
```

### Context Preservation

Before memory compaction, BDB injects reminders about critical files:

```
=== CRITICAL CONTEXT FILES ===
These files contain important project context. Reference them if you lose track:
  - docs/plans/implementation.md
  - CLAUDE.md
```

## LLM Providers

BDB supports multiple LLM providers for the stop and tool-failure hooks:

### OpenAI (default)
```yaml
llm:
  provider: openai
  model: gpt-4o-mini  # or gpt-4o, gpt-4-turbo
  api_key: sk-...
```

### Anthropic
```yaml
llm:
  provider: anthropic
  model: claude-3-5-haiku-20241022
  api_key: sk-ant-...
```

### Ollama (local)
```yaml
llm:
  provider: ollama
  model: llama3.2
  base_url: http://localhost:11434  # optional
```

### Azure OpenAI
```yaml
llm:
  provider: azure
  model: gpt-4o-mini  # Actual model name (for Langfuse cost tracking)
  deployment: my-gpt4o-deployment  # Azure deployment name
  base_url: https://your-resource.openai.azure.com
  api_key_env: AZURE_OPENAI_API_KEY
  api_version: 2024-08-01-preview  # optional
```

**Note:** Azure OpenAI uses deployment names for API calls, but you must specify the actual `model` name (e.g., `gpt-4o-mini`) for accurate cost tracking in Langfuse.

## Development

```bash
# Clone and install in development mode
git clone https://github.com/cognaterra/better-drinking-bird
cd better-drinking-bird
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src/
```

## Logging

Logs are written to `~/.bdb/`:
- `supervisor.log` - Normal operation logs
- `errors.log` - Error details and tracebacks

Enable debug mode:
```bash
BDB_DEBUG=1 bdb run
```

## Tracing (Langfuse)

BDB supports [Langfuse](https://langfuse.com) for observability and cost tracking. Each hook invocation creates a trace with:

- LLM generations with exact model identification
- Token usage (input/output) for cost calculation
- Decision scores (allow/block/kill)
- Error events

### Setup

```yaml
# In ~/.bdbrc
tracing:
  enabled: true
  # Use environment variables (recommended)
  public_key_env: LANGFUSE_PUBLIC_KEY
  secret_key_env: LANGFUSE_SECRET_KEY
  # Or direct keys
  # public_key: pk-lf-...
  # secret_key: sk-lf-...
  host: https://cloud.langfuse.com  # or self-hosted URL
```

Set your environment variables:
```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
```

### What Gets Traced

| Hook | Trace Name | Generations |
|------|-----------|-------------|
| Stop | `bdb_stop` | `evaluate_stop_decision` |
| Tool Failure | `bdb_posttoolusefailure` | `generate_recovery_advice` |

Each trace includes the actual model returned by the API (not just the requested model), ensuring accurate cost attribution even when using model aliases or fallbacks.

## License

MIT License - see [LICENSE](LICENSE)

## Credits

Inspired by the autonomous agent supervision needs of the Claude Code community.

Named after Homer Simpson's ingenious work automation solution.
