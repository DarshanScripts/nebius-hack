# Member 4 backlog

One line per item: status — what — why — where — trigger.

- BLOCKED — Live Nemotron scene generation/repair (`json_prompt`) — the key in the dev shell gets `403 Authorization failed` on chat completions — `demo --only s02` — owner supplies the project NVIDIA key (or runs the command with their `.env`).
- UNVERIFIED — `tool_calling` mode (create_agent + ToolStrategy + validate tool) against Nemotron — depends on member 1's capability check — `agent.draft_with_tools` — member 1 records `NEMOTRON_STRUCTURED_MODE=tool_calling`.
- DONE 2026-10-18 — `renderer/Dockerfile` build and in-container render (full mock path, run 20261018-1537).
- BLOCKED — Compose must run `renderer` with the same uid:gid as `api` (`user:`), otherwise publishing into api-created scene dirs fails with EACCES (reproduced with the default uid 10001) — member 1's `infra/compose.yml` — member 1 wires the renderer service.
- UNVERIFIED — Rendering with the REAL character PNGs (image path itself verified with MOCK transparent PNGs, run 20261018-1453) — assets not in the repo yet — `shell.tsx` `Characters` — owner adds `assets/characters/{sundar,jensen}.png`.
- UNVERIFIED — Remotion licence terms for a 5-person team — Remotion is free for individuals/small companies, paid above that; not checked for this hackathon use — `renderer/package.json` — before any use beyond the hackathon demo.
- DEFERRED — Worker-side recomputation of `context_hash`/`timeline_hash` — member 1 owns canonical hashing in `contracts/validation.py`; worker only checks build hashes equal the context fields — `renderer/src/jobs.ts checkRequest` — once `contracts/validation.py` lands, mirror or call it.
- DEFERRED — Bundle caching across jobs (each job runs a fresh webpack bundle, ~3-5 s) — fine at ~12 s per preview — `render-job.ts` — if preview latency becomes a demo problem.
- DEFERRED — Blocking outbound network from the render browser — generated code is policy-checked and the public dir holds only job assets, but Chromium itself is not network-sandboxed — `render-job.ts chromiumOptions` / container network policy — before exposing beyond the internal compose network.
- DEFERRED — Remove `.bootstrap` PYTHONPATH from the README commands — `contracts/models.py` not on main yet — README — member 1 publishes contracts.
- WONTFIX (accepted limitation, 2026-10-18) — Edit router is pattern-based (21 editable / 19 locked phrasings tested); an unseen phrasing can still be mis-sorted. Not pursued further because no rule set or model removes that risk, and the damage is bounded by design: a wrong refusal shows a reason and the user rephrases or selects the scene; a wrong acceptance can only change that one scene's visuals (audio, timing, dialogue and other scenes are locked by the contract and the build hash checks). Plan 8.7 requirements are met. Reopen only if a real mis-route is reported — add that phrasing to the router tests — `router.py`.
- BLOCKED — Core's invalid-structured-output error code must contain an output-problem marker (INVALID/SCHEMA/PARSE/VALIDATION/STRUCTURED/JSON) for repairs to count — contract does not fix the code — `service._is_output_problem` — member 1 confirms the code used in `Runtime.structured`.
- WONTFIX — Static check of computed font sizes — not decidable statically; kit components enforce the minimum — `source-check.ts`.
