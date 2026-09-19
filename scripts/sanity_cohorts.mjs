import assert from "node:assert/strict";
import { reconcileCohorts } from "./reconcile-cohorts.mjs";

const source = {
  traces: {
    kept: { retain: "pinned", pinned: true, retentionReason: "useful baseline", provenance: "abc", compareWith: ["gone"] },
    gone: { patterns: ["old"] },
  },
  cohorts: { sample: { question: "Example?", traceIds: ["kept", "gone"] } },
  nextRun: { compareWith: ["gone", "kept"] },
  obsolete: {}, unavailableHistoricalTraceIds: {},
};
const before = structuredClone(source);
const store = { runs: { kept: {}, fresh: {} } };
const result = reconcileCohorts(source, store);
assert.deepEqual(source, before);
assert.deepEqual(result.uncataloged, ["fresh"]);
assert.equal(result.catalog.traces.kept.provenance, "abc");
assert.equal(result.catalog.traces.kept.historicalAssessment, "useful baseline");
assert.equal("retain" in result.catalog.traces.kept, false);
assert.equal("pinned" in result.catalog.traces.kept, false);
assert.equal("gone" in result.catalog.traces, false);
assert.deepEqual(result.catalog.traces.kept.compareWith, []);
assert.deepEqual(result.catalog.cohorts.sample.traceIds, ["kept"]);
assert.deepEqual(result.catalog.nextRun.compareWith, ["kept"]);
assert.equal(reconcileCohorts(result.catalog, store).changed, false);
assert.deepEqual(reconcileCohorts(source, { runs: {} }).catalog.traces, {});
assert.throws(() => reconcileCohorts(source, {}));
assert.throws(() => reconcileCohorts(source, { runs: [] }));
console.log("cohort reconciliation sanity ok");
