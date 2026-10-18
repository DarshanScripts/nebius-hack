# Member 4 backlog

One line per item: status — what — why — where — trigger.

- DONE 2026-10-18 — Live Nemotron scene generation (`json_prompt`, one scene, thinking disabled) — run `scenes-live3/live-report-20261018-1605.json`.
- BLOCKED — Live generation through core's `AppRuntime` times out (hidden reasoning, 180 s) — needs `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` (or a setting) and `NEMOTRON_TIMEOUT_SECONDS≥300` in `backend/core/runtime.py` — Member 1 applies the change.
- UNVERIFIED — Six-scene live run, live edit and live final; the new no-overlap guide rule — only one live scene was generated — next live session.
- UNVERIFIED — `tool_calling` mode (create_agent + ToolStrategy + validate tool) against Nemotron — depends on member 1's capability check — `agent.draft_with_tools` — member 1 records `NEMOTRON_STRUCTURED_MODE=tool_calling`.
- DONE 2026-10-18 — `renderer/Dockerfile` build and in-container render (full mock path, run 20261018-1537).
- DONE 2026-10-18 (not needed) — Compose `user:` for the renderer: `infra/Dockerfile.api` also runs as uid 10001, matching the renderer image; host `output/` must be writable by 10001.
- UNVERIFIED — Rendering with the REAL character PNGs (image path itself verified with MOCK transparent PNGs, run 20261018-1453) — assets not in the repo yet — `shell.tsx` `Characters` — owner adds `assets/characters/{sundar,jensen}.png`.
- UNVERIFIED — Remotion licence terms for a 5-person team — Remotion is free for individuals/small companies, paid above that; not checked for this hackathon use — `renderer/package.json` — before any use beyond the hackathon demo.
- DEFERRED — Worker-side recomputation of `context_hash`/`timeline_hash` — member 1 owns canonical hashing in `contracts/validation.py`; worker only checks build hashes equal the context fields — `renderer/src/jobs.ts checkRequest` — once `contracts/validation.py` lands, mirror or call it.
- DEFERRED — Bundle caching across jobs (each job runs a fresh webpack bundle, ~3-5 s) — fine at ~12 s per preview — `render-job.ts` — if preview latency becomes a demo problem.
- DEFERRED — Blocking outbound network from the render browser — generated code is policy-checked and the public dir holds only job assets, but Chromium itself is not network-sandboxed — `render-job.ts chromiumOptions` / container network policy — before exposing beyond the internal compose network.
- DONE 2026-10-18 — `.bootstrap` PYTHONPATH removed from the README (contracts come from the merged seed).
- WONTFIX (accepted limitation, 2026-10-18) — Edit router is pattern-based (21 editable / 19 locked phrasings tested); an unseen phrasing can still be mis-sorted. Not pursued further because no rule set or model removes that risk, and the damage is bounded by design: a wrong refusal shows a reason and the user rephrases or selects the scene; a wrong acceptance can only change that one scene's visuals (audio, timing, dialogue and other scenes are locked by the contract and the build hash checks). Plan 8.7 requirements are met. Reopen only if a real mis-route is reported — add that phrasing to the router tests — `router.py`.
- DONE 2026-10-18 — Core's structured-output error codes checked in `backend/core/runtime.py`: `STRUCTURED_OUTPUT_INVALID` → repair; `MODEL_REQUEST_FAILED`/`MISSING_CONFIGURATION`/`MOCK_LLM_DISABLED` → raised (tests cover the classifier).
- WONTFIX — Static check of computed font sizes — not decidable statically; kit components enforce the minimum — `source-check.ts`.
