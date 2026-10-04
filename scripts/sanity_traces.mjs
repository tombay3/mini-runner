import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Read-only sanity check of local evidence, without gameplay or detailed schema tests.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const directory = path.resolve(root, process.env.AGENT_DATA_DIR || "__data1");
const errors = [];
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const check = (condition, message) => { if (!condition) errors.push(message); };

function read(name, version, collections) {
  const filename = path.join(directory, name);
  if (!existsSync(filename)) {
    console.log(`${name}: missing (not initialized)`);
    return null;
  }
  try {
    const store = JSON.parse(readFileSync(filename, "utf8"));
    if (!object(store) || store.version !== version || collections.some((key) => !object(store[key]))) {
      throw new Error(`expected version ${version} and ${collections.join("/")} objects`);
    }
    for (const key of collections) {
      for (const [id, entry] of Object.entries(store[key])) {
        check(id.length > 0 && object(entry), `${name}: invalid ${key} entry ${id}`);
      }
    }
    console.log(`${name}: ${collections.map((key) => `${Object.keys(store[key]).length} ${key}`).join(", ")}`);
    return store;
  } catch (error) {
    errors.push(`${name}: ${error.message}`);
    return null;
  }
}

const recordings = read("recordings.json", 1, ["records"]);
const traces = read("agent-traces.json", 4, ["runs"]);
const catalog = read("trace-cohorts.json", 1, ["traces", "cohorts"]);
const hasTrace = (id) => typeof id === "string" && Object.hasOwn(traces?.runs || {}, id);

for (const [id, record] of Object.entries(recordings?.records || {})) {
  if (!object(record)) continue;
  check(record.id === id && object(record.demo), `recordings.json: invalid recording ${id}`);
  if (record.source === "agent") {
    check(record.traceId === id, `recordings.json: agent recording/trace ID mismatch ${id}`);
  }
  if (record.traceId && !hasTrace(record.traceId)) {
    console.warn(`recordings.json: linked trace unavailable ${record.traceId}`);
  }
}
for (const [id, run] of Object.entries(traces?.runs || {})) {
  if (!object(run)) continue;
  check(run.id === id && Array.isArray(run.steps), `agent-traces.json: invalid run ${id}`);
}
for (const id of Object.keys(catalog?.traces || {})) {
  check(hasTrace(id), `trace-cohorts.json: stale trace ${id}`);
}
for (const [id, cohort] of Object.entries(catalog?.cohorts || {})) {
  if (!object(cohort)) continue;
  check(Array.isArray(cohort.traceIds), `trace-cohorts.json: invalid cohort ${id}`);
  for (const traceId of Array.isArray(cohort.traceIds) ? cohort.traceIds : []) {
    check(hasTrace(traceId), `trace-cohorts.json: cohort ${id} links missing trace ${traceId}`);
  }
}
const uncataloged = Object.keys(traces?.runs || {}).filter((id) => !Object.hasOwn(catalog?.traces || {}, id));
if (uncataloged.length) console.warn(`Uncataloged traces: ${uncataloged.length}; review with npm run cohorts:check.`);

const logPath = path.join(directory, "agent-debug.log");
if (!existsSync(logPath)) {
  console.log("agent-debug.log: missing (debug logging is optional)");
} else {
  try {
    const bytes = readFileSync(logPath);
    const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    check(!text.includes("\0"), "agent-debug.log: unexpected binary content");
    check(!text.trim() || text.trimStart().startsWith("===== agent-model-io "),
      "agent-debug.log: unrecognized log format");
    console.log(`agent-debug.log: ${bytes.length} bytes`);
  } catch (error) {
    errors.push(`agent-debug.log: ${error.message}`);
  }
}

if (errors.length) {
  for (const error of errors) console.error(error);
  process.exitCode = 1;
} else {
  console.log("trace data sanity ok");
}
