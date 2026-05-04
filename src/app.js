import "./style.css";

const BOOT_KEY = "__lodeRunnerViteBoot";
const STATUS_ID = "boot-status";

const legacyScripts = [
  "/game/lodeRunner.wData.js",
  "/game/lib/preloadjs-0.6.2.min.js",
  "/game/lib/soundjs-0.6.2.min.js",
  "/game/lib/tweenjs-0.6.2.min.js",
  "/game/lib/easeljs-0.7.1.min.js",
  "/game/flag32Id.js",
  "/game/lodeRunner.gameVerName.js",
  "/game/lodeRunner.v.classic.js",
  "/game/lodeRunner.v.professional.js",
  "/game/lodeRunner.v.revenge.js",
  "/game/lodeRunner.v.fanBookMod.js",
  "/game/lodeRunner.v.championship.js",
  "/game/lodeRunner.storage.js",
  "/game/lodeRunner.def.js",
  "/game/lodeRunner.key.js",
  "/game/lodeRunner.misc.js",
  "/game/lodeRunner.hiscore.js",
  "/game/lodeRunner.info.js",
  "/game/lodeRunner.menu.js",
  "/game/lodeRunner.iconClass.js",
  "/game/lodeRunner.runner.js",
  "/game/lodeRunner.guard.js",
  "/game/lodeRunner.demo.js",
  "/game/lodeRunner.demoData1.js",
  "/game/lodeRunner.edit.js",
  "/game/lodeRunner.preload.js",
  "/game/lodeRunner.colorTheme.js",
  "/game/lodeRunner.colorSelector.js",
  "/game/lodeRunner.gamepad.js",
  "/game/lodeRunner.main.js",
  "/game/lodeRunner.win.js",
  "/game/lodeRunner.share.js",
];

if (!window[BOOT_KEY]) {
  window[BOOT_KEY] = {
    started: false,
    initialized: false,
    promise: null,
  };
}

const bootState = window[BOOT_KEY];

if (!bootState.started) {
  bootState.started = true;
  bootState.promise = bootLegacyGame();
}

async function bootLegacyGame() {
  try {
    ensureLegacyCanvas();
    ensureTitle();
    ensureFavicon();
    ensureBaseHref();
    ensureStatusNode();

    setStatus("Loading legacy runtime...");
    await loadLegacyScripts();

    if (typeof window.init !== "function") {
      throw new Error("Legacy runtime loaded, but window.init is missing.");
    }
    if (!bootState.initialized) {
      bootState.initialized = true;
      setStatus("Starting game...");
      window.init();
    }
    clearStatus();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    showError(message);
    throw error;
  }
}

function ensureLegacyCanvas() {
  if (!document.getElementById("canvas")) {
    throw new Error("Missing legacy root canvas element '#canvas'.");
  }
}

function ensureTitle() {
  document.title = "Lode Runner Web Game";
}

function ensureFavicon() {
  let icon = document.querySelector("link[rel~='icon']");
  if (!icon) {
    icon = document.createElement("link");
    icon.rel = "shortcut icon";
    document.head.appendChild(icon);
  }
  icon.href = "/game/lodeRunner.ico";
}

function ensureBaseHref() {
  let base = document.querySelector("base[data-legacy-base='true']");
  if (!base) {
    base = document.createElement("base");
    base.setAttribute("data-legacy-base", "true");
    document.head.prepend(base);
  }
  base.href = "/game/";
}

function ensureStatusNode() {
  if (document.getElementById(STATUS_ID)) {
    return;
  }
  const status = document.createElement("div");
  status.id = STATUS_ID;
  status.setAttribute("role", "status");
  status.hidden = true;
  document.body.appendChild(status);
}

function setStatus(message) {
  const status = document.getElementById(STATUS_ID);
  if (!status) {
    return;
  }
  status.hidden = false;
  status.className = "boot-status";
  status.textContent = message;
}

function clearStatus() {
  const status = document.getElementById(STATUS_ID);
  if (!status) {
    return;
  }
  status.hidden = true;
  status.textContent = "";
  status.className = "boot-status";
}

function showError(message) {
  const status = document.getElementById(STATUS_ID) || createFallbackStatus();
  status.hidden = false;
  status.className = "boot-status boot-status-error";
  status.textContent = `Failed to boot Lode Runner: ${message}`;
}

function createFallbackStatus() {
  const status = document.createElement("div");
  status.id = STATUS_ID;
  document.body.appendChild(status);
  return status;
}

async function loadLegacyScripts() {
  for (const src of legacyScripts) {
    await loadScript(src);
  }
}

function loadScript(src) {
  const existing = document.querySelector(`script[data-legacy-src="${src}"]`);
  if (existing?.dataset.loaded === "true") {
    return Promise.resolve();
  }
  if (existing?.dataset.loading === "true") {
    return new Promise((resolve, reject) => {
      existing.addEventListener("load", resolve, { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error(`Failed to load legacy script: ${src}`)),
        { once: true },
      );
    });
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = false;
    script.dataset.legacySrc = src;
    script.dataset.loading = "true";
    script.onload = () => {
      script.dataset.loading = "false";
      script.dataset.loaded = "true";
      resolve();
    };
    script.onerror = () => {
      script.dataset.loading = "false";
      reject(new Error(`Failed to load legacy script: ${src}`));
    };
    document.head.appendChild(script);
  });
}
