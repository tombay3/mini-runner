import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const pythonPath = path.join(
  rootDir,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);

if (!existsSync(pythonPath)) {
  console.error(`Project virtualenv Python not found: ${pythonPath}`);
  console.error("Create .venv and install Jupyter Notebook before running npm run notebook.");
  process.exit(1);
}

const child = spawn(pythonPath, [
  "-m", "notebook",
  "--no-browser",
  "--ip=0.0.0.0",
  "--port=8081",
  "--ServerApp.port_retries=0",
  `--ServerApp.root_dir=${rootDir}`,
  "--JupyterNotebookApp.default_url=/notebooks/trace-analytics.ipynb",
  "--IdentityProvider.token=",
  "--PasswordIdentityProvider.hashed_password=",
  ...process.argv.slice(2),
], { cwd: rootDir, stdio: "inherit" });

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
