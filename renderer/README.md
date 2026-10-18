# Render worker (member 4)

Node 22 + Remotion 4.0.534 (all Remotion packages pinned to the same exact version).
Full documentation — routes, render path, generated-source policy, commands, acceptance results
and blockers — is in [`backend/modules/scenes/README.md`](../backend/modules/scenes/README.md).

```bash
npm ci
npm run typecheck && npm test
ARTIFACT_ROOT=./output RENDER_WORKER_TOKEN=<secret> npm run worker   # :8001
docker build -t reel-renderer .
```

Files: `src/scene-kit.tsx` (the only module generated scenes may import), `src/shell.tsx`
(background, title, captions, characters, audio, boundary fades), `src/Reel.tsx`,
`src/ScenePreview.tsx`, `src/Root.tsx`/`src/index.ts` (compositions), `src/worker.ts` (HTTP +
queue), `src/jobs.ts` (input checks, job staging, execution), `src/render-job.ts` (child render
process), `src/source-check.ts` (policy + type-check), `src/types/contracts.ts` (mirror of
`contracts/models.py`).
