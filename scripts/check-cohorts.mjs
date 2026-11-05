import { existsSync, readFileSync, writeFileSync, renameSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");

// A pair is usable evidence only when identities, streams and endpoint agree.
export function pairProblem(id, recording, trace) {
  if (!object(recording) || !object(trace) || recording.id !== id ||
      recording.traceId !== id || trace.id !== id) return "recording/trace UUID mismatch or missing object";
  const demo = recording.demo;
  if (!object(demo) || ![demo.action, demo.goldDrop, demo.bornPos].every(Array.isArray) ||
      !Number.isFinite(demo.time) || demo.action.length % 2 !== 0) return "incomplete recording streams";
  if (!Array.isArray(trace.steps) || !trace.steps.length ||
      !object(trace.outcome?.finalState)) return "missing trace decisions or terminal state";
  if (trace.outcome.finalState.tick !== demo.time ||
      trace.steps.some(step => !Number.isFinite(step.state?.tick) || step.state.tick > demo.time)) {
    return "recording/trace endpoint mismatch";
  }
  for (const field of ["playData", "level"]) {
    if (String(recording[field]) !== String(trace[field])) return `${field} mismatch`;
  }
  if (Boolean(demo.godMode) !== Boolean(trace.outcome.finalState.godMode)) return "mode mismatch";
  return null;
}

function validateReference(reference) {
  if (!object(reference) || typeof reference.path !== "string" ||
      !Array.isArray(reference.keys) || reference.keys.some(key => typeof key !== "string")) {
    throw new Error("expected archive reference {path,keys:[...]}");
  }
}

export function readArchiveReference(root, reference, cache = new Map()) {
  validateReference(reference);
  const path = resolve(root, reference.path);
  if (!cache.has(path)) cache.set(path, JSON.parse(readFileSync(path, "utf8")));
  const data = cache.get(path);
  let value = data;
  for (const key of reference.keys) {
    if (!object(value) || !Object.hasOwn(value, key)) throw new Error(`missing archive key ${key}`);
    value = value[key];
  }
  return value;
}

// Reconciliation preserves historical findings, groups and comparison links.
export function reconcileCohorts(catalog, store, recordings = { records: {} }, options = {}) {
  if (store?.version !== 4) throw new Error("Expected v4 trace store {version:4,runs}");
  if (![catalog?.traces, catalog?.cohorts, store?.runs, recordings?.records].every(object)) {
    throw new Error("Expected catalog traces/cohorts, trace-store runs and recording-store records objects");
  }
  const result = structuredClone(catalog);
  const root = options.root ?? rootDir, cache = new Map();
  const readReference = options.readReference ?? (ref => readArchiveReference(root, ref, cache));
  const referenceExists = options.referenceExists ?? (ref => existsSync(resolve(root, ref.path)));
  const errors = [], warnings = [], counts = { live: 0, archived: 0, missing: 0 };
  for (const [id, entry] of Object.entries(result.traces)) {
    if (!object(entry)) { errors.push(`${id}: invalid catalog entry`); continue; }
    let archived = false;
    if (entry.archive) {
      try {
        const { recording, trace } = entry.archive;
        validateReference(recording); validateReference(trace);
        archived = referenceExists(recording) && referenceExists(trace);
        if (archived && options.verifyArchives) {
          const problem = pairProblem(id, readReference(recording), readReference(trace));
          if (problem) throw new Error(problem);
        }
      } catch (error) { archived = false; errors.push(`${id}: ${error.message}`); }
    }
    const live = !pairProblem(id, recordings.records[id], store.runs[id]);
    entry.dataStatus = live ? "live" : archived ? "archived" : "missing";
    counts[entry.dataStatus]++;
    for (const group of entry.cohortIds ?? []) {
      if (!result.cohorts[group]?.traceIds?.includes(id)) warnings.push(`${id}: missing reciprocal cohort membership ${group}`);
    }
  }
  for (const [id, group] of Object.entries(result.cohorts)) {
    if (!object(group) || !Array.isArray(group.traceIds)) { errors.push(`${id}: invalid cohort`); continue; }
    for (const traceId of group.traceIds) {
      if (result.traces[traceId] && !result.traces[traceId].cohortIds?.includes(id)) warnings.push(`${id}: missing reciprocal trace membership ${traceId}`);
    }
  }
  result.policy ??= {};
  result.policy.evidenceAvailabilityRule =
    "Preserve historical entries, groups and links. dataStatus reports live pairs, locally present archive references, or missing data. Archive contents require explicit verification; unavailable history is skipped.";
  result.policy.pinAuthority = "recordings.json owns pin state; the catalog never duplicates it.";
  return {
    catalog: result, counts, errors, warnings,
    changed: JSON.stringify(result) !== JSON.stringify(catalog),
    uncataloged: Object.keys(store.runs).filter(id => !Object.hasOwn(result.traces, id) &&
      !pairProblem(id, recordings.records[id], store.runs[id])),
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    if (args.some(arg => !["--write", "--verify-archives"].includes(arg))) {
      throw new Error("Usage: npm run cohorts:check -- [--write] [--verify-archives]");
    }
    const directory = resolve(rootDir, process.env.AGENT_DATA_DIR || "__data1");
    const path = resolve(directory, "trace-cohorts.json");
    const tracePath = resolve(directory, "agent-traces.json"), recordPath = resolve(directory, "recordings.json");
    function read(path) {
      try { return readFileSync(path, "utf8"); }
      catch (error) { if (error.code === "ENOENT") return null; throw error; }
    }
    const original = read(path), traceOriginal = read(tracePath), recordOriginal = read(recordPath);
    const catalog = original === null ? { version: 1, updatedAt: null, cohorts: {}, traces: {} } : JSON.parse(original);
    const result = reconcileCohorts(catalog,
      traceOriginal === null ? { version: 4, runs: {} } : JSON.parse(traceOriginal),
      recordOriginal === null ? { records: {} } : JSON.parse(recordOriginal),
      { verifyArchives: args.includes("--verify-archives") });
    const needsWrite = original === null || result.changed;
    if (args.includes("--write") && needsWrite && !result.errors.length) {
      if (read(path) !== original || read(tracePath) !== traceOriginal || read(recordPath) !== recordOriginal) {
        throw new Error("Stores changed during reconciliation; retry when idle");
      }
      result.catalog.updatedAt = new Date().toISOString();
      const serialized = JSON.stringify(result.catalog, null, 2) + "\n";
      if (original === null) writeFileSync(path, serialized, { flag: "wx" });
      else {
        writeFileSync(`${path}.bak`, original);
        const temporary = `${path}.${process.pid}.tmp`;
        writeFileSync(temporary, serialized); renameSync(temporary, path);
      }
      console.log("Updated catalog evidence status; historical findings and groups preserved.");
    } else console.log(needsWrite
      ? original === null ? "Catalog missing; create it with --write."
        : "Catalog availability or policy needs updating; run with --write."
      : "Catalog evidence status is current.");
    console.log(`Live pairs: ${result.counts.live}. Local archive references: ${result.counts.archived}.`);
    if (args.includes("--verify-archives")) console.log("Local archive contents verified where available.");
    console.log(`Uncataloged traces requiring review: ${result.uncataloged.length}`);
    for (const id of result.uncataloged) console.log(id);
    for (const warning of result.warnings) console.warn(warning);
    for (const error of result.errors) console.error(error);
    if (result.errors.length || result.uncataloged.length || (needsWrite && !args.includes("--write"))) process.exitCode = 1;
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
