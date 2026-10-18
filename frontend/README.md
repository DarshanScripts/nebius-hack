# Reel Lab editor (member 5)

React, Vite, and TypeScript editor for the six-scene reel workflow. The frontend consumes the frozen section 10 API in `plan.md`. It sends no provider requests and reads only `VITE_API_BASE_URL` from the root environment.

## Run

Requires Node 22+ and npm. From `frontend/`:

```bash
npm ci
npm run dev
```

Open `http://localhost:5173/?mock=1` for the standalone frontend fixture. Omit `?mock=1` to call the backend. For local backend development, set `VITE_API_BASE_URL=http://localhost:8000` in the root `.env`; for the deployed same-origin proxy, build with `VITE_API_BASE_URL=`. Restart/rebuild Vite after changing this build-time value. No API, NVIDIA, Tavily, voice, or Nebius credentials are needed for the frontend fixture.

```bash
npm run build
npm run preview
```

The standalone mock lives in `src/api/mock.ts`. It uses the same `EditorApi` interface as `src/api/client.ts`, persists projects in browser local storage, publishes delayed research/dialogue/images/audio/timeline states, and completes previews in order `s03, s01, s06, s02, s05, s04`. The six slots remain ordered. Its local MP4 is a two-second, silent placeholder, and its WAV is silent. Both are visibly marked mock; they do not demonstrate real rendering or Chatterbox/WhisperX output. The browser player gets audio only from the preview MP4, never a second simultaneous stream. The mock timeline uses the required frame gaps and scene boundaries `[0,273,543,813,1083,1353,1800]`.

## Reproduce the acceptance flow

1. Open `/?mock=1` and press **Create reel** with the prefilled topic.
2. Watch research and sources, twelve dialogue turns, and audio with word timing appear. Expand **Research & sources** and any **Audio & word timing** row.
3. Watch scene completion events arrive as `3, 1, 6, 2, 5, 4`; the right pane stays numbered `01` through `06`.
4. Select scene 6 and send the prefilled correction. Its previous preview stays playable while revision 2 runs. Scene 1–5 preview URLs remain unchanged.
5. Press **Stitch reel**. Watch progress, download the mock placeholder MP4, then refresh. The project, events, revision, and download link restore from local storage. With the backend, refresh instead loads persisted snapshot/events through `/api`.

An automated Edge/Playwright check exercises the same path. Start the dev server in one terminal, then run:

```bash
npm run smoke
```

Set `SMOKE_URL` to another frontend origin or `SMOKE_BROWSER` to a Playwright Chromium channel if needed. Browser screenshots are written to ignored `.artifacts/`.

## Checks performed

On 2026-10-18, a clean `npm ci` and `npm run build` passed TypeScript and Vite production compilation. `npm run smoke` passed against the built preview in headless Microsoft Edge and reported:

```json
{"slots":[1,2,3,4,5,6],"completion_order":[3,1,6,2,5,4],"scene_6_revision":2,"other_preview_urls_unchanged":true,"stitch_download":true,"refresh_restored":true,"mobile_navigation":true,"api_requests":0}
```

## Integration boundary

The live API wrapper covers project list/create/read, cursor events, edit, retry, Stitch, and encoded artifact URLs. Its routes and request bodies were compared with `origin/feat/m1-platform` on 2026-10-18. That platform branch is not yet merged into `main`; a real backend round trip, persistence across an API restart, and real MP4/audio acceptance remain for integration. The UI expects the exact snake_case fields and revision lifecycle from `plan.md`; no shared contract change is requested. The selected NVIDIA Nemotron endpoint is server configuration and is never called or configured in the browser.
