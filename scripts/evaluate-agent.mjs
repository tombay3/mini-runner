import { spawn, spawnSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.dirname(scriptsDir);
const options = parseArgs(process.argv.slice(2));
const startedServers = [];
let browser = null;

try {
  await ensureServer("backend", "http://127.0.0.1:8080/api/health", ["run", "api"]);
  await ensureServer("frontend", options.baseUrl, ["run", "dev", "--", "--host", "127.0.0.1"]);

  const executablePath = resolveBrowserExecutable(options.browserExecutable);
  browser = await chromium.launch({
    executablePath,
    headless: !options.headful,
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  page.setDefaultTimeout(0);

  const url = new URL(options.baseUrl);
  if (options.profile) {
    url.searchParams.set("profile", options.profile);
  }
  await page.goto(url.href, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__lodeRunnerEvaluation?.ready(), null, {
    timeout: options.startupTimeoutMs,
  });

  const runtimeStatus = await page.evaluate(() => window.__lodeRunnerEvaluation.status());
  if (options.smoke) {
    process.stdout.write(`${JSON.stringify({ smoke: "ok", runtimeStatus }, null, 2)}\n`);
  }

  const attempts = [];
  for (let index = 0; index < (options.smoke ? 0 : options.runs); index += 1) {
    const startedAt = new Date().toISOString();
    process.stdout.write(`run ${index + 1}/${options.runs} ... `);
    const result = await page.evaluate(() => window.__lodeRunnerEvaluation.runAttempt());
    const trace = result.traceId
      ? await page.evaluate(async (traceId) => {
          const response = await fetch(`/api/agent/traces/${encodeURIComponent(traceId)}`);
          if (!response.ok) {
            throw new Error(`trace request failed: ${response.status}`);
          }
          return response.json();
        }, result.traceId)
      : null;
    const attempt = summarizeAttempt(index + 1, startedAt, result, trace);
    attempts.push(attempt);
    process.stdout.write(
      `${attempt.result} steps=${attempt.stepCount ?? "-"} ` +
        `time=${attempt.demoTime ?? "-"} reason=${attempt.failureReason ?? "-"}\n`,
    );
  }

  const report = buildReport(options, attempts, executablePath);
  process.stdout.write(`${JSON.stringify(report.summary, null, 2)}\n`);
  if (options.output) {
    const outputPath = path.resolve(rootDir, options.output);
    writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`report: ${outputPath}\n`);
  }
  if (report.summary.normalModeViolations > 0) {
    process.exitCode = 3;
  } else if (report.summary.integrityViolations > 0) {
    process.exitCode = 4;
  } else if (report.summary.meetsThreshold === false) {
    process.exitCode = 2;
  }
} catch (error) {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exitCode = 1;
} finally {
  await browser?.close().catch(() => {});
  if (!options.keepServers) {
    for (const server of startedServers.reverse()) {
      stopServer(server);
    }
  }
}

function parseArgs(args) {
  const result = {
    runs: 10,
    threshold: null,
    profile: null,
    baseUrl: "http://127.0.0.1:8283/",
    browserExecutable: process.env.EVAL_BROWSER_EXECUTABLE || null,
    startupTimeoutMs: 30_000,
    headful: false,
    keepServers: false,
    output: null,
    smoke: false,
  };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    const next = () => {
      index += 1;
      if (index >= args.length) {
        throw new Error(`${arg} requires a value`);
      }
      return args[index];
    };
    if (arg === "--runs") result.runs = positiveInteger(next(), "runs", 100);
    else if (arg === "--threshold") result.threshold = normalizeThreshold(next());
    else if (arg === "--profile") result.profile = nonempty(next(), "profile");
    else if (arg === "--base-url") result.baseUrl = new URL(next()).href;
    else if (arg === "--browser") result.browserExecutable = nonempty(next(), "browser");
    else if (arg === "--startup-timeout-ms") {
      result.startupTimeoutMs = positiveInteger(next(), "startup timeout", 300_000);
    } else if (arg === "--output") result.output = nonempty(next(), "output");
    else if (arg === "--headful") result.headful = true;
    else if (arg === "--keep-servers") result.keepServers = true;
    else if (arg === "--smoke") result.smoke = true;
    else if (arg === "--help") {
      printHelp();
      process.exit(0);
    } else {
      throw new Error(`unknown argument: ${arg}`);
    }
  }
  return result;
}

function positiveInteger(value, label, maximum) {
  const number = Number(value);
  if (!Number.isInteger(number) || number < 1 || number > maximum) {
    throw new Error(`${label} must be an integer from 1 to ${maximum}`);
  }
  return number;
}

function normalizeThreshold(value) {
  let number = Number(value);
  if (number > 1 && number <= 100) number /= 100;
  if (!Number.isFinite(number) || number < 0 || number > 1) {
    throw new Error("threshold must be between 0 and 1, or a percentage from 0 to 100");
  }
  return number;
}

function nonempty(value, label) {
  const text = String(value).trim();
  if (!text) throw new Error(`${label} must not be empty`);
  return text;
}

async function ensureServer(name, healthUrl, npmArgs) {
  if (await isReady(healthUrl)) {
    process.stdout.write(`${name}: reusing ${healthUrl}\n`);
    return;
  }
  const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
  const child = spawn(npmCommand, npmArgs, {
    cwd: rootDir,
    detached: process.platform !== "win32",
    env: { ...process.env, NO_COLOR: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const log = [];
  const collect = (chunk) => {
    log.push(String(chunk));
    while (log.join("").length > 12_000) log.shift();
  };
  child.stdout.on("data", collect);
  child.stderr.on("data", collect);
  startedServers.push({ name, child, log });

  const deadline = Date.now() + options.startupTimeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`${name} exited before startup:\n${log.join("")}`);
    }
    if (await isReady(healthUrl)) {
      process.stdout.write(`${name}: started ${healthUrl}\n`);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`${name} did not become ready:\n${log.join("")}`);
}

async function isReady(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 800);
  try {
    const response = await fetch(url, { signal: controller.signal });
    return response.ok;
  } catch (_error) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function stopServer(server) {
  if (server.child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(server.child.pid), "/T", "/F"], { stdio: "ignore" });
  } else {
    try {
      process.kill(-server.child.pid, "SIGTERM");
    } catch (_error) {
      server.child.kill("SIGTERM");
    }
  }
}

function resolveBrowserExecutable(explicitPath) {
  const candidates = [
    explicitPath,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    process.env.PROGRAMFILES
      ? path.join(process.env.PROGRAMFILES, "Google/Chrome/Application/chrome.exe")
      : null,
    process.env["PROGRAMFILES(X86)"]
      ? path.join(process.env["PROGRAMFILES(X86)"], "Google/Chrome/Application/chrome.exe")
      : null,
  ].filter(Boolean);
  const match = candidates.find((candidate) => existsSync(candidate));
  if (!match) {
    throw new Error(
      "Chrome or Chromium was not found. Set EVAL_BROWSER_EXECUTABLE or pass --browser.",
    );
  }
  return match;
}

function summarizeAttempt(number, startedAt, result, trace) {
  const steps = Array.isArray(trace?.steps) ? trace.steps : [];
  const kinds = {};
  let fallbacks = 0;
  let confirmedStalls = 0;
  let retries = 0;
  for (const step of steps) {
    const kind = step?.selectedCandidateKind || "unknown";
    kinds[kind] = (kinds[kind] || 0) + 1;
    if (step?.validation?.fallbackUsed) fallbacks += 1;
    if (step?.stallSupervisor?.severity === "stalled") confirmedStalls += 1;
    if (step?.stallSupervisor?.retryAttempted) retries += 1;
  }
  const terminalGodMode = trace?.outcome?.finalState?.godMode;
  const recordedGodMode = Number(result.godMode);
  const contextValid =
    Number(result.playData) === 1 &&
    Number(result.level) === 1 &&
    Number(trace?.playData) === 1 &&
    Number(trace?.level) === 1 &&
    steps.every((step) => Number(step?.playData) === 1 && Number(step?.level) === 1) &&
    Number(trace?.outcome?.finalState?.playData) === 1 &&
    Number(trace?.outcome?.finalState?.level) === 1;
  const ticks = steps.map((step) => Number(step?.state?.tick));
  const timelineValid = ticks.every(
    (tick, index) => Number.isFinite(tick) && (index === 0 || tick >= ticks[index - 1]),
  );
  return {
    number,
    startedAt,
    finishedAt: new Date().toISOString(),
    id: result.id,
    traceId: result.traceId,
    result: result.result,
    failureReason: result.failureReason,
    demoTime: result.demoTime,
    stepCount: trace?.stepCount ?? steps.length,
    model: trace?.model ?? null,
    normalMode: recordedGodMode === 0 && terminalGodMode === false,
    contextValid,
    timelineValid,
    outcome: trace?.outcome ?? null,
    fallbacks,
    confirmedStalls,
    retries,
    selectedCandidateKinds: kinds,
  };
}

function buildReport(config, attempts, executablePath) {
  const successes = attempts.filter((attempt) => attempt.result === "success").length;
  const failures = attempts.length - successes;
  const successRate = attempts.length ? successes / attempts.length : 0;
  const normalModeViolations = attempts.filter((attempt) => !attempt.normalMode).length;
  const integrityViolations = attempts.filter(
    (attempt) => !attempt.contextValid || !attempt.timelineValid,
  ).length;
  return {
    version: 1,
    createdAt: new Date().toISOString(),
    config: {
      runs: config.runs,
      threshold: config.threshold,
      profile: config.profile,
      baseUrl: config.baseUrl,
      browserExecutable: executablePath,
    },
    summary: {
      runs: attempts.length,
      successes,
      failures,
      successRate,
      threshold: config.threshold,
      meetsThreshold: config.threshold === null ? null : successRate >= config.threshold,
      normalModeViolations,
      integrityViolations,
    },
    attempts,
  };
}

function printHelp() {
  process.stdout.write(`Usage: npm run evaluate -- [options]\n\n`);
  process.stdout.write(`  --runs N                 fresh attempts (default: 10, maximum: 100)\n`);
  process.stdout.write(`  --threshold RATE         required success rate, e.g. 0.95 or 95\n`);
  process.stdout.write(`  --profile NAME           model profile passed through the browser URL\n`);
  process.stdout.write(`  --browser PATH           Chrome/Chromium executable\n`);
  process.stdout.write(`  --base-url URL           wrapper URL (default: http://127.0.0.1:8283/)\n`);
  process.stdout.write(`  --headful                 show the evaluation browser\n`);
  process.stdout.write(`  --keep-servers            leave servers started by this command running\n`);
  process.stdout.write(`  --output PATH             write the full JSON report under the repository\n`);
  process.stdout.write(`  --smoke                   verify browser/runtime startup without an LLM run\n`);
}
