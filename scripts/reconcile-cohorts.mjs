import { readFileSync, writeFileSync, renameSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

// Mechanical reconciliation only: never infer provenance or diagnostic labels.
export function reconcileCohorts(catalog, store) {
  if (!catalog?.traces || !catalog?.cohorts || !store?.runs ||
      [catalog.traces, catalog.cohorts, store.runs].some(
        (value) => typeof value !== "object" || Array.isArray(value))) {
    throw new Error("Expected catalog traces/cohorts and trace-store runs objects");
  }
  const result = structuredClone(catalog);
  const live = new Set(Object.keys(store.runs));
  for (const [id, entry] of Object.entries(result.traces)) {
    if (!live.has(id)) {
      delete result.traces[id];
      continue;
    }
    delete entry.retain;
    delete entry.pinned;
    if (entry.retentionReason !== undefined) {
      entry.historicalAssessment ??= entry.retentionReason;
      delete entry.retentionReason;
    }
  }
  function pruneReferences(value) {
    if (!value || typeof value !== "object") return;
    for (const [key, item] of Object.entries(value)) {
      if (["traceIds", "compareWith"].includes(key) && Array.isArray(item)) {
        value[key] = item.filter((id) => live.has(id));
      } else {
        pruneReferences(item);
      }
    }
  }
  pruneReferences(result);
  delete result.obsolete;
  delete result.unavailableHistoricalTraceIds;
  result.policy ??= {};
  result.policy.evidenceAvailabilityRule =
    "agent-traces.json owns availability; prune missing trace entries and comparison links during reconciliation.";
  result.policy.pinAuthority =
    "recordings.json owns pin state; the catalog never duplicates it.";
  return {
    catalog: result,
    changed: JSON.stringify(result) !== JSON.stringify(catalog),
    uncataloged: [...live].filter((id) => !Object.hasOwn(result.traces, id)),
  };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    if (args.length > 1 || (args.length && args[0] !== "--write")) {
      throw new Error("Usage: npm run cohorts:check -- [--write]");
    }
    const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
    const data = resolve(root, process.env.AGENT_DATA_DIR || "__data1");
    const path = resolve(data, "trace-cohorts.json");
    const tracePath = resolve(data, "agent-traces.json");
    const original = readFileSync(path, "utf8");
    const traceOriginal = readFileSync(tracePath, "utf8");
    const result = reconcileCohorts(JSON.parse(original), JSON.parse(traceOriginal));
    if (args.includes("--write") && result.changed) {
      if (readFileSync(path, "utf8") !== original ||
          readFileSync(tracePath, "utf8") !== traceOriginal) {
        throw new Error("Stores changed during reconciliation; retry when idle");
      }
      result.catalog.updatedAt = new Date().toISOString();
      const backup = `${path}.bak`;
      writeFileSync(backup, original);
      const temporary = `${path}.${process.pid}.tmp`;
      writeFileSync(temporary, JSON.stringify(result.catalog, null, 2) + "\n");
      renameSync(temporary, path);
      console.log(`Reconciled catalog only; previous version: ${backup}`);
    } else {
      console.log(result.changed ? "Catalog needs reconciliation (--write)." : "Catalog links are consistent.");
    }
    console.log(`Uncataloged traces requiring review: ${result.uncataloged.length}`);
    for (const id of result.uncataloged) console.log(id);
    if (result.uncataloged.length || (result.changed && !args.includes("--write"))) {
      process.exitCode = 1;
    }
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
