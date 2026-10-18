# Member 4 backlog

One line per item: status — what — why — where — trigger.

- BLOCKED — Live Nemotron scene generation/repair (`json_prompt`) — the key in the dev shell gets `403 Authorization failed` on chat completions — `demo --only s02` — owner supplies the project NVIDIA key (or runs the command with their `.env`).
- UNVERIFIED — `tool_calling` mode (create_agent + ToolStrategy + validate tool) against Nemotron — depends on member 1's capability check — `agent.draft_with_tools` — member 1 records `NEMOTRON_STRUCTURED_MODE=tool_calling`.
- UNVERIFIED — `renderer/Dockerfile` build and in-container render — image build downloads several hundred MB (base image, npm deps, Chrome Headless Shell); asked before downloading — `renderer/Dockerfile` — approval to build locally, or member 1's first deploy on the Nebius VM.
- UNVERIFIED — Rendering with real character PNGs — assets not in the repo yet — `shell.tsx` `Characters` — owner adds `assets/characters/{sundar,jensen}.png` (member 1 copies them into the project namespace).
- UNVERIFIED — Remotion licence terms for a 5-person team — Remotion is free for individuals/small companies, paid above that; not checked for this hackathon use — `renderer/package.json` — before any use beyond the hackathon demo.
- DEFERRED — Worker-side recomputation of `context_hash`/`timeline_hash` — member 1 owns canonical hashing in `contracts/validation.py`; worker only checks build hashes equal the context fields — `renderer/src/jobs.ts checkRequest` — once `contracts/validation.py` lands, mirror or call it.
- DEFERRED — Bundle caching across jobs (each job runs a fresh webpack bundle, ~3-5 s) — fine at ~12 s per preview — `render-job.ts` — if preview latency becomes a demo problem.
- DEFERRED — Blocking outbound network from the render browser — generated code is policy-checked and the public dir holds only job assets, but Chromium itself is not network-sandboxed — `render-job.ts chromiumOptions` / container network policy — before exposing beyond the internal compose network.
- DEFERRED — Remove `.bootstrap` PYTHONPATH from the README commands — `contracts/models.py` not on main yet — README — member 1 publishes contracts.
