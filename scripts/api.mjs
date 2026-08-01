import { spawn } from "node:child_process";
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
  console.error("Create .venv and install requirements.txt before running npm run api.");
  process.exit(1);
}

const child = spawn(
  pythonPath,
  [path.join(rootDir, "app.py"), ...process.argv.slice(2)],
  {
    cwd: rootDir,
    stdio: "inherit",
  },
);

child.on("error", (error) => {
  console.error(error.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
