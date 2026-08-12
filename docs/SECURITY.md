# Prototype security model

AgentSEO never executes an uploaded API description. Server URLs, callbacks, examples, and schema
strings are treated as data. OpenAPI documents are size-limited, parsed with `yaml.safe_load`, and
limited to local `$ref` resolution. Benchmarks run only against built-in deterministic sandboxes.

Phase 1 also includes environment-based secrets, strict request schemas, CORS allowlisting, a basic
per-process request limit, bounded model loops, task-count limits, provider timeouts, and logs that
exclude API keys. Production deployment still requires authentication/authorization, tenant-aware
row isolation, encrypted secret storage, distributed rate limits, malware/content scanning, audit
retention policy, dependency/image scanning, outbound network policy, and hardened sandbox process
isolation. The current in-process sandbox is safe for synthetic examples, not untrusted customer code.

