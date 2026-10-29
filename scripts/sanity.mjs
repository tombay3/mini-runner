import { spawnSync } from "node:child_process";
import path from "node:path";
import { projectPython, rootDir } from "./launch-python.mjs";

const scriptsDir = path.join(rootDir, "scripts");
let pythonPath;
try {
  pythonPath = projectPython("Create .venv and install requirements.txt before running npm test.");
} catch (error) {
  console.error(error.message);
  process.exit(1);
}

run(pythonPath, [path.join(scriptsDir, "sanity_backend.py")]);
run(process.execPath, [path.join(scriptsDir, "sanity_frontend.mjs")]);

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
