import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptsDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.dirname(scriptsDir);
const pythonPath = path.join(
  rootDir,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);

if (!existsSync(pythonPath)) {
  console.error(`Project virtualenv Python not found: ${pythonPath}`);
  console.error("Create .venv and install requirements.txt before running npm test.");
  process.exit(1);
}

run(pythonPath, [path.join(scriptsDir, "sanity_backend.py")]);
run(process.execPath, [path.join(scriptsDir, "sanity_frontend.mjs")]);
run(process.execPath, [path.join(scriptsDir, "sanity_candidate_lanes.mjs")]);

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: rootDir,
    stdio: "inherit",
  });
  if (result.error) {
    console.error(result.error.message);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}
