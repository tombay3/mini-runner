# Add Vite Root Entrypoint for Legacy Lode Runner

## Summary
Create a new root `index.html` plus `src/app.js` and `src/style.css` so Vite can serve and build the project from `/`, while preserving the existing `/public/game` CreateJS runtime unchanged.

The new entrypoint uses a direct same-document global load strategy, not an `iframe`. It recreates the minimum DOM and path context the legacy app expects, then loads the existing scripts in the same order as `public/game/lodeRunner.html`, and finally calls `window.init()` once.

## Implementation Changes
- Add root `index.html` as the Vite entry module.
- Include the legacy root canvas markup:
  `<div class="canvas"><canvas id="canvas" width="960" height="400"></canvas></div>`
- Load `/src/app.js` with an absolute path so it is not affected by the legacy base-path override.

- Add `src/app.js` as the legacy bootloader.
- Insert a one-time boot guard on `window` so Vite dev/HMR does not double-load scripts or double-call `init()`.
- Set `document.title` and favicon to mirror the old entrypoint.
- Insert a `<base href="/game/">` element before loading legacy scripts so all legacy relative asset URLs such as `image/...`, `sound/...`, `cursor/...`, `./lib/...`, and `lodeRunner.ico` resolve exactly as they do in `public/game/lodeRunner.html`.
- Load legacy scripts sequentially with dynamically created `<script>` tags, preserving the current order from `public/game/lodeRunner.html`.
- Load the wrapper hook [public/game/lodeRunner.agentHooks.js](../public/game/lodeRunner.agentHooks.js) immediately after `lodeRunner.main.js` so the AI agent can step the legacy game without modifying the legacy source files.
- Use `/game/...` absolute URLs for the bootloader’s own script-loading list so the loader itself is independent of the `<base>` tag.
- After the last script finishes, verify `window.init` exists and call it once.
- Surface a clear runtime error in the page if any legacy script fails to load or `init` is missing.

- Add `src/style.css` for a minimal host shell.
- Reset `html` and `body` to full-height with zero margin.
- Keep the page game-only, with no extra Vite UI.
- Avoid layout rules that would interfere with the legacy runtime’s absolute-positioned canvases and overlays appended to `document.body`.
- Provide a neutral background, hidden overflow, and a small boot/error status overlay.
- Provide wrapper icon-rail styling for recording playback, AI solve, god mode, and fullscreen controls without interfering with legacy canvas positioning.

- Keep `public/game/*` unchanged.
- Do not edit legacy HTML, JS, asset paths, or preload manifests.
- Do not convert legacy files into ES modules.
- Do not rewrite relative asset paths in the legacy runtime.

## Boot Sequence
1. Vite serves `index.html`.
2. `index.html` loads `/src/app.js`.
3. `app.js` installs the boot guard, sets favicon/title, inserts `<base href="/game/">`, and confirms the root `#canvas` already exists.
4. `app.js` loads the legacy libraries and game scripts in the same order as the old HTML entrypoint.
5. After all scripts are ready, `app.js` calls `window.init()`.
6. The legacy runtime takes over and appends its additional canvases and UI layers to `document.body` as before.

## Wrapper Additions
- [src/recording.js](../src/recording.js) owns the left icon rail, recording API integration, god-mode star, and fullscreen soft-restart behavior.
- [src/agent.js](../src/agent.js) owns the browser-side AI loop and saves success/failure demos through the recording API.
- Fullscreen enter/exit intentionally restarts the legacy game from the welcome flow so the legacy `init()` sizing math reruns for the new viewport.

## Test Plan
- Run `npm run build` and confirm the root Vite entry still builds.
- Run `npm run dev` and open `/`.
- Confirm the game boots from the new root page.
- Confirm cover screen, preload, and main menu render correctly.
- Confirm image, sound, cursor, and theme assets load from `/game/...`.
- Smoke-test one gameplay path.
- Confirm the main canvas and overlay canvases behave normally.
- Smoke-test one demo path.
- Confirm demo data still loads and demo playback still starts.
- Refresh the page in dev mode.
- Confirm the boot guard prevents duplicate script injection or double initialization.

## Assumptions
- Host mode is direct globals.
- Root page is game-only with no added shell UI.
- The existing global-script CreateJS architecture remains the source of truth.
- Compatibility target is the current browser runtime already supporting the legacy game; no refactor to modules or TypeScript is part of this change.
