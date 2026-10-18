# Nebius Devlab operator handoff

Use the existing team project `group08-project` and Devlab
`azure-pinniped-devlab-2` (`devlab-e05bkzg40ksp13hx8z`). The project
has no standalone Compute VM. Do not create another GPU resource.

The current application runs from two persistent directories:

- `/home/jovyan/work/nebius-speech`: Chatterbox Turbo on loopback 8002,
  WhisperX on loopback 8003, private reference WAVs under
  `assets/voices/{sundar,jensen}/reference.wav`, separate Python 3.11
  environments, and the Node 22 conda environment `.node`.
- `/home/jovyan/work/nebius-app`: merged source, Python 3.12 `.venv`,
  API on loopback 8000, authenticated Remotion worker on loopback 8001,
  built editor preview on loopback 5173, and shared `output/` artifacts.

The private `.env` in each workspace is mode 600. Do not print, copy into
Git, or upload either file to an unrelated destination. The app env has the
Tavily and Nebius Token Factory keys, its internal bearer keys, and
`ASSETS_ROOT=/home/jovyan/work/nebius-speech/assets`. The worker receives
only its render settings. The two speech apps require their separate
bearer keys.

## After a Devlab restart

1. Open **Serverless AI → Devlabs → azure-pinniped-devlab-2 → Open** and sign
   in to Jupyter. The tunnel hostname may have changed.
2. In a terminal, check `jupyter server extension list` for
   `jupyter_server_proxy`. Check both speech loopback `/health` routes
   for `status: ok`, `model_loaded: true`, `device: cuda`.
3. Inspect process arguments and working directories before relaunching
   any absent process. Follow [infra/README.md](README.md) for exact
   launch commands and logs. Do not start duplicate Uvicorn or Node workers.
4. Update `VITE_PREVIEW_HOST` and `FRONTEND_ORIGIN` in the app's private
   `.env` for a changed tunnel host. Build the frontend again with
   `VITE_BASE_PATH=./` and `VITE_API_BASE_URL=/proxy/8000`.
5. Verify authenticated Jupyter routes `/proxy/8002/health`,
   `/proxy/8003/health`, `/proxy/8000/api/health`, then open
   `/proxy/5173/`.

The API and worker share
`ARTIFACT_ROOT=/home/jovyan/work/nebius-app/output`. The editor's
same-origin API request goes to `/proxy/8000/api`, and the API calls both
speech services over loopback. No public speech or worker port is needed.

As of 2026-10-18, both GPU services passed a short real-reference synthesis
and word-alignment check for each speaker, the live API/worker/editor health
checks passed, and a WhatsApp calling example reached Tavily research. A
completed live reel and speaker image PNGs are still outstanding. Review
[agents.md](../agents.md) for the latest project state and next action.
