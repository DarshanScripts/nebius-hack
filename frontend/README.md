# ResearchReel editor

React, Vite, and TypeScript editor for the six-scene reel workflow. The frontend consumes the frozen section 10 API in `plan.md`. It sends no provider requests and reads only `VITE_API_BASE_URL` from the root environment.

## Visual theme

The cinematic theme branch starts from member 1's integrated `11cc617`. The supplied
reference informs the near-black backgrounds, blue accents, light Inter typography,
quiet borders, rounded surfaces, and split composition. This applies to the full
editor: new film, project library, sidebar, research/sources, dialogue/audio, six
scene slots, corrections, render progress, download, loading, errors, and dialogs.

`src/styles.css` defines shared color tokens for dark (default) and light themes.
The header theme switch persists the choice locally. Both themes support reduced
motion, visible keyboard focus, native dialog focus trapping/Escape dismissal,
independent editor scrolling, and mobile activity/storyboard tabs. Media is shown
in its original colors; changing the interface does not alter rendered films.

The new-film view offers topic suggestions and an example-topic dialog. Projects
can be searched and filtered by completion state. The activity trace is expandable
so it does not push the research and dialogue out of view. All controls use the
existing API client and revision/timing contracts.

Fonts and the NASA/JPL-Caltech Saturn image are bundled locally; see
`src/assets/README.md` for attribution. The image is inspiration, not a pre-rendered
example film. The app makes no external font or image requests.

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

The collapsed sidebar controls have distinct destinations: grid opens the project library, plus opens the new-reel form, and film opens the current reel with its scene pane selected. Film is disabled until a reel exists. The active icon follows the displayed view.

## Reproduce the acceptance flow

1. Open `/?mock=1`, enter a topic (or choose a suggestion), and press the circular **Create reel** arrow.
2. Watch research and sources, twelve dialogue turns, and audio with word timing appear. Expand **Research & sources** and any **Audio & word timing** row.
3. Expand **Activity** to see completion events arrive as `3, 1, 6, 2, 5, 4`; the right pane stays numbered `01` through `06`.
4. Select scene 6, type “Please correct scene six: make the packet diagram clearer”, and send it. Its previous preview stays playable while revision 2 runs. Scene 1–5 preview URLs remain unchanged.
5. Press **Stitch reel**. Watch progress, download the mock placeholder MP4, then refresh. The project, events, revision, and download link restore from local storage. With the backend, refresh instead loads persisted snapshot/events through `/api`.

An automated Edge/Playwright check exercises the same path. Start the dev server in one terminal, then run:

```bash
npm run smoke
npm run smoke:api
```

Set `SMOKE_URL` to another frontend origin or `SMOKE_BROWSER` to a Playwright Chromium channel if needed. Browser screenshots are written to ignored `.artifacts/`.
`smoke:api` uses intercepted HTTP responses to check the real client routes, request body, progressive snapshots, cursor events, and refresh restoration without contacting providers. Run it against the same dev or preview server, without `?mock=1`.

## Theme acceptance checks

The production build and both browser checks run against the built preview, with
headless Microsoft Edge:

```bash
npm run build
npm run preview -- --port 5174 --strictPort
# In a second terminal:
SMOKE_URL=http://127.0.0.1:5174 npm run smoke
SMOKE_URL=http://127.0.0.1:5174 npm run smoke:api
```

The updated smoke flow covers dark/light selection and refresh persistence, topic
suggestions, dialogs, the empty library, sidebar navigation, project search and
filters, all six progressive previews, research/audio expansion, scene-six edits,
Stitch, download, and refresh. It checks no horizontal overflow at desktop, tablet,
390 px and 320 px widths, with no browser exceptions or API calls in mock mode.
The HTTP check covers the real client with intercepted responses, including
loading, a recoverable stage error, and retry.

Screenshots in ignored `.artifacts/theme-*.png` cover the new-film screen, library,
editor, expanded research/audio, both themes, rendering/download, error/loading,
and mobile layouts. These tests use fixture media; live inference and final-video
quality remain backend acceptance checks.

## Earlier integration checks

On 2026-10-18, a clean `npm ci` and `npm run build` passed TypeScript and Vite production compilation. After merging platform seed `d3dfba6`, the build and `npm run smoke` passed again against the built preview in headless Microsoft Edge and reported:

```json
{"slots":[1,2,3,4,5,6],"completion_order":[3,1,6,2,5,4],"scene_6_revision":2,"other_preview_urls_unchanged":true,"stitch_download":true,"refresh_restored":true,"mobile_navigation":true,"api_requests":0}
```

`npm run smoke:api` passed with `{"http_create":true,"progressive_snapshot":true,"refresh_restored":true,"event_deduplicated":true,"scene_slots":6}`. This tests the browser against a contract-shaped HTTP fixture, not the running FastAPI service.

## Integration boundary

The live API wrapper covers project list/create/read, cursor events, edit, retry, Stitch, and encoded artifact URLs. Its routes and request bodies were compared with the platform API on 2026-10-18. Platform seed `d3dfba6` is now an ancestor of this branch, but the team modules are not yet integrated on `main`. A real backend round trip, persistence across an API restart, and real MP4/audio acceptance remain for integration. The UI expects the exact snake_case fields and revision lifecycle from `plan.md`; no shared contract change is requested. The selected NVIDIA Nemotron endpoint is server configuration and is never called or configured in the browser.

## Member 1 integration steps

1. Fetch and merge `origin/feat/m5-cinematic-theme` into the integration branch. The theme is based on integrated commit `11cc617` and only changes frontend files. No backend or schema change is needed.
2. Build the web image from the repository root with `docker compose --env-file .env -f infra/compose.yml -f infra/compose.gpu.yml up -d --build`. `infra/Dockerfile.web` runs `npm ci` and `npm run build` in `frontend/`. Set `VITE_API_BASE_URL` to empty for the deployed same-origin `/api` proxy. Only this public URL is read by the frontend.
3. Open the deployed site without `?mock=1`. Create a project with server `MOCK_MODE=true` first and verify six slots, incremental research/dialogue/audio, out-of-order ready previews, a scene-six edit, Stitch, and a refresh. This uses real API persistence and Remotion rendering once members 2–4 are merged. Then repeat with live mode after provider and GPU readiness checks.
4. Check `GET /api/health`, the browser network calls to `/api/projects`, `/events`, `/edits`, `/stitch`, and byte-range playback/download through `/api/artifacts/{key}`. Keep the final 1800-frame and audible-word checks with the backend/renderer acceptance run.
