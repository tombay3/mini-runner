import { spawn, spawnSync } from "node:child_process";
import { existsSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

import {
  candidateLane,
  candidateLaneSet,
  classifySingletonStep,
  decisionClass,
  isProgressOnlyLowRiskStep,
} from "./candidate-lanes.mjs";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.dirname(scriptsDir);
const options = parseArgs(process.argv.slice(2));
const startedServers = [];
let browser = null;
let executablePath = null;
const attempts = [];

try {
  await ensureServer("backend", "http://127.0.0.1:8080/api/health", ["run", "api"]);
  await ensureServer("frontend", options.baseUrl, ["run", "dev", "--", "--host", "127.0.0.1"]);

  executablePath = resolveBrowserExecutable(options.browserExecutable);
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
  if (process.env.AGENT_CANDIDATE_MODE) {
    url.searchParams.set("candidateMode", process.env.AGENT_CANDIDATE_MODE);
  }
  if (process.env.AGENT_CANDIDATE_LIMIT) {
    url.searchParams.set("candidateLimit", process.env.AGENT_CANDIDATE_LIMIT);
  }
  await page.goto(url.href, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => window.__lodeRunnerEvaluation?.ready(), null, {
    timeout: options.startupTimeoutMs,
  });

  const runtimeStatus = await page.evaluate(() => window.__lodeRunnerEvaluation.status());
  if (options.smoke) {
    process.stdout.write(`${JSON.stringify({ smoke: "ok", runtimeStatus }, null, 2)}\n`);
  }

  for (let index = 0; index < (options.smoke ? 0 : options.runs); index += 1) {
    const startedAt = new Date().toISOString();
    process.stdout.write(`run ${index + 1}/${options.runs} ... `);
    let result;
    try {
      result = await page.evaluate(() => window.__lodeRunnerEvaluation.runAttempt());
    } catch (error) {
      // A wrapper reload can destroy Playwright's execution context between
      // attempts. Reattach to the page and retry that attempt instead of
      // abandoning the remaining campaign runs.
      if (!String(error?.message || error).includes("Execution context was destroyed")) {
        throw error;
      }
      await page.goto(url.href, { waitUntil: "domcontentloaded" });
      await page.waitForFunction(() => window.__lodeRunnerEvaluation?.ready(), null, {
        timeout: options.startupTimeoutMs,
      });
      result = await page.evaluate(() => window.__lodeRunnerEvaluation.runAttempt());
    }
    const trace = result.traceId ? await fetchTraceAfterPersistence(page, result.traceId) : null;
    const attempt = summarizeAttempt(index + 1, startedAt, result, trace);
    attempts.push(attempt);
    process.stdout.write(
      `${attempt.result} steps=${attempt.stepCount ?? "-"} ` +
        `time=${attempt.demoTime ?? "-"} reason=${attempt.failureReason ?? "-"}\n`,
    );
    if (
      options.target !== null &&
      attempts.filter((item) => item.result === "success").length >= options.target
    ) {
      process.stdout.write(`early stop: reached ${options.target} successful run(s)\n`);
      break;
    }
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
  } else if (report.summary.meetsTarget === false) {
    process.exitCode = 2;
  }
} catch (error) {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  if (options.output) {
    const outputPath = path.resolve(rootDir, options.output);
    const failureReport = {
      options,
      executablePath,
      attempts,
      error: error instanceof Error ? error.stack || error.message : String(error),
      completedAt: new Date().toISOString(),
    };
    writeFileSync(outputPath, `${JSON.stringify(failureReport, null, 2)}\n`, "utf8");
    process.stderr.write(`failure report: ${outputPath}\n`);
  }
  process.exitCode = 1;
} finally {
  await closeBrowser(browser);
  if (!options.keepServers) {
    for (const server of startedServers.reverse()) {
      await stopServer(server);
    }
  }
}

async function fetchTraceAfterPersistence(page, traceId) {
  const deadline = Date.now() + 10_000;
  let lastStatus = "unavailable";
  while (Date.now() < deadline) {
    const response = await page.evaluate(async (id) => {
      const result = await fetch(`/api/agent/traces/${encodeURIComponent(id)}`);
      return { ok: result.ok, status: result.status, body: result.ok ? await result.json() : null };
    }, traceId);
    if (response.ok) return response.body;
    lastStatus = response.status;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`trace request failed after persistence wait: ${lastStatus}`);
}

function parseArgs(args) {
  const result = {
    runs: 10,
    target: null,
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
    else if (arg === "--target") result.target = positiveInteger(next(), "target", 100);
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

async function stopServer(server) {
  if (server.child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(server.child.pid), "/T", "/F"], { stdio: "ignore" });
    return;
  }
  signalServerGroup(server.child, "SIGTERM");
  const exited = await Promise.race([
    new Promise((resolve) => server.child.once("exit", () => resolve(true))),
    new Promise((resolve) => setTimeout(() => resolve(false), 5_000)),
  ]);
  if (!exited && server.child.exitCode === null) {
    signalServerGroup(server.child, "SIGKILL");
  }
}

function signalServerGroup(child, signal) {
  try {
    process.kill(-child.pid, signal);
  } catch (_error) {
    child.kill(signal);
  }
}

async function closeBrowser(activeBrowser) {
  if (!activeBrowser) return;
  await Promise.race([
    activeBrowser.close().catch(() => {}),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
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
  const candidatePoolKinds = {};
  const candidatePoolLanes = {};
  const decisionClasses = {};
  const singletonClassifications = {};
  const candidateAuditDispositions = {};
  const candidateGapClassifications = {};
  let maxCandidatePool = 0;
  let progressOnlyLowRiskSteps = 0;
  let progressOnlyLowRiskSingleChoiceSteps = 0;
  let progressOnlyLowRiskMultiChoiceSteps = 0;
  const stepCorrelations = [];
  const notableCorrelations = [];
  let fallbacks = 0;
  let confirmedLoops = 0;
  let suppressedCandidates = 0;
  for (const [stepIndex, step] of steps.entries()) {
    const kind = step?.selectedCandidateKind || "unknown";
    kinds[kind] = (kinds[kind] || 0) + 1;
    if (step?.validation?.fallbackUsed) fallbacks += 1;
    if (step?.loopMonitor?.active) confirmedLoops += 1;
    suppressedCandidates += Array.isArray(step?.loopMonitor?.suppressedCandidates)
      ? step.loopMonitor.suppressedCandidates.length
      : 0;
    maxCandidatePool = Math.max(maxCandidatePool, Array.isArray(step?.candidates) ? step.candidates.length : 0);
    for (const candidate of step?.candidates || []) {
      const candidateKind = candidate?.kind || "unknown";
      candidatePoolKinds[candidateKind] = (candidatePoolKinds[candidateKind] || 0) + 1;
      const lane = candidateLane(candidate);
      candidatePoolLanes[lane] = (candidatePoolLanes[lane] || 0) + 1;
    }
    const modelSelection = step?.modelSelection || {};
    const candidates = Array.isArray(step?.candidates) ? step.candidates : [];
    const selectedKind = step?.selectedCandidateKind || "unknown";
    const selectedLane = candidateLane(selectedKind);
    const stepDecisionClass = decisionClass(step);
    const singleton = classifySingletonStep(step);
    decisionClasses[stepDecisionClass] = (decisionClasses[stepDecisionClass] || 0) + 1;
    if (singleton) {
      singletonClassifications[singleton.classification] =
        (singletonClassifications[singleton.classification] || 0) + 1;
    }
    if (isProgressOnlyLowRiskStep(step)) {
      progressOnlyLowRiskSteps += 1;
      if (candidates.length === 1) progressOnlyLowRiskSingleChoiceSteps += 1;
      else progressOnlyLowRiskMultiChoiceSteps += 1;
    }
    const candidateAudit = Array.isArray(step?.candidateAudit) ? step.candidateAudit : [];
    for (const item of candidateAudit) {
      const disposition = item?.disposition || "unknown";
      candidateAuditDispositions[disposition] =
        (candidateAuditDispositions[disposition] || 0) + 1;
      const gapClass = auditGapClassification(disposition);
      if (gapClass) {
        candidateGapClassifications[gapClass] =
          (candidateGapClassifications[gapClass] || 0) + 1;
      }
    }
    if (singleton?.classification?.startsWith("suspicious_") && !candidateAudit.length) {
      candidateGapClassifications.missing_proposal =
        (candidateGapClassifications.missing_proposal || 0) + 1;
    }
    if (candidates.length > 1) {
      const unselectedProgress = candidates.filter(
        (candidate) => candidateLane(candidate) === "progress" && candidate?.id !== step?.selectedCandidateId,
      ).length;
      if (unselectedProgress) {
        candidateGapClassifications.exposed_not_selected =
          (candidateGapClassifications.exposed_not_selected || 0) + unselectedProgress;
      }
    }
    const nextStep = steps[stepIndex + 1];
    const selectedNoProgress =
      selectedLane === "progress" && nextStep && !stepMadeProgress(step, nextStep);
    if (selectedNoProgress) {
      candidateGapClassifications.selected_no_progress =
        (candidateGapClassifications.selected_no_progress || 0) + 1;
    }
    let classification = "no_gap";
    if (!candidates.length) classification = "no_generated_candidates";
    else if (step?.validation?.fallbackUsed) classification = "model_selection_fallback";
    else if (stepDecisionClass === "progress_only_low_risk" && selectedLane !== "progress") {
      classification = "progress_only_selection_gap";
    }
    const correlation = {
      stepIndex,
      tick: step?.state?.tick,
      requestedCandidateId: modelSelection.requestedCandidateId,
      selectedCandidateId: step?.selectedCandidateId,
      selectedCandidateKind: selectedKind,
      selectedCandidateLane: selectedLane,
      selectedScore: candidates.find((candidate) => candidate?.id === step?.selectedCandidateId)?.score ?? null,
      candidateLanes: candidateLaneSet(candidates),
      decisionClass: stepDecisionClass,
      singletonClassification: singleton?.classification || null,
      singletonEvidence: singleton?.evidence || [],
      reasoningContent: modelSelection.reasoningContent || "",
      declaredRationale: modelSelection.declaredRationale || "",
      parseError: modelSelection.parseError || null,
      candidates: candidates.map((candidate) => ({
        id: candidate?.id,
        kind: candidate?.kind,
        lane: candidateLane(candidate),
        score: candidate?.score,
        target: candidate?.target,
        firstAction: candidate?.firstAction,
      })),
      candidateAudit,
      selectedNoProgress: Boolean(selectedNoProgress),
      classification,
    };
    stepCorrelations.push(correlation);
    if (classification !== "no_gap" || !correlation.reasoningContent) {
      notableCorrelations.push({
        stepIndex,
        classification,
        selectedCandidateId: correlation.selectedCandidateId,
        reasoningPresent: Boolean(correlation.reasoningContent),
      });
    }
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
    confirmedLoops,
    suppressedCandidates,
    selectedCandidateKinds: kinds,
    candidatePoolKinds,
    candidatePoolLanes,
    decisionClasses,
    singletonClassifications,
    candidateAuditDispositions,
    candidateGapClassifications,
    maxCandidatePool,
    progressOnlyLowRiskSteps,
    progressOnlyLowRiskSingleChoiceSteps,
    progressOnlyLowRiskMultiChoiceSteps,
    stepCorrelations,
    notableCorrelations,
  };
}

function auditGapClassification(disposition) {
  return {
    physical_rejection: "physical_rejection",
    safety_rejection: "safety_rejection",
    loop_suppressed: "loop_suppressed",
    deduplicated: "deduplicated",
    limit_truncated: "limit_truncated",
    validated: "validated_not_exposed",
  }[disposition] || null;
}

function stepMadeProgress(step, nextStep) {
  const before = step?.state || {};
  const after = nextStep?.state || {};
  const beforeRunner = before.runner || {};
  const afterRunner = after.runner || {};
  const beforeGold = Number(before?.gold?.remainingCount);
  const afterGold = Number(after?.gold?.remainingCount);
  if (Number.isFinite(beforeGold) && Number.isFinite(afterGold) && afterGold < beforeGold) {
    return true;
  }
  return ["x", "y", "xOffset", "yOffset"].some(
    (field) => Number(beforeRunner[field]) !== Number(afterRunner[field]),
  );
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
    version: 2,
    createdAt: new Date().toISOString(),
    config: {
      runs: config.runs,
      target: config.target,
      profile: config.profile,
      baseUrl: config.baseUrl,
      browserExecutable: executablePath,
    },
    summary: {
      runs: attempts.length,
      successes,
      failures,
      successRate,
      target: config.target,
      meetsTarget: config.target === null ? null : successes >= config.target,
      normalModeViolations,
      integrityViolations,
    },
    attempts,
  };
}

function printHelp() {
  process.stdout.write(`Usage: npm run evaluate -- [options]\n\n`);
  process.stdout.write(`  --runs N                 fresh attempts (default: 10, maximum: 100)\n`);
  process.stdout.write(`  --target N               stop after N successful runs (maximum 100)\n`);
  process.stdout.write(`  --profile NAME           model profile passed through the browser URL\n`);
  process.stdout.write(`  --browser PATH           Chrome/Chromium executable\n`);
  process.stdout.write(`  --base-url URL           wrapper URL (default: http://127.0.0.1:8283/)\n`);
  process.stdout.write(`  --headful                 show the evaluation browser\n`);
  process.stdout.write(`  --keep-servers            leave servers started by this command running\n`);
  process.stdout.write(`  --output PATH             write the full JSON report under the repository\n`);
  process.stdout.write(`  --smoke                   verify browser/runtime startup without an LLM run\n`);
}
