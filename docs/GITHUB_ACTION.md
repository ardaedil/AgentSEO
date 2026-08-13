# GitHub Action

```yaml
permissions:
  contents: read
  pull-requests: write

steps:
  - uses: actions/checkout@v4
    with: {fetch-depth: 0}
  - uses: agentseo/compatibility-check@v1
    env:
      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
    with:
      spec: ./openapi.yaml
      task_suite: ./contracts
      models: openai:gpt-4.1-mini,anthropic:claude-sonnet-5,google:gemini-3.6-flash
      cost_limit: "1.00"
      max_tasks: "50"
      fail_on_warning: "false"
      baseline_ref: origin/main
```

Provider keys belong in GitHub Actions secrets and are passed only as environment variables. They
must never be committed. The composite Action loads the baseline spec with `git show`, writes a
Markdown step summary, upserts one PR comment, exposes verdict outputs, and propagates AgentSEO's
process exit code to the status check. The repository's own workflow uses `mock:reliable` and no paid
keys; its output is infrastructure validation only.
