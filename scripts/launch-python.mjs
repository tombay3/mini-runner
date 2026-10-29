import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

export function projectPython(guidance, root = rootDir) {
  const executable = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  if (!existsSync(executable)) {
    throw new Error(`Project virtualenv Python not found: ${executable}\n${guidance}`);
  }
  return executable;
}

export function launchPython(args, guidance) {
  let executable;
  try {
    executable = projectPython(guidance);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
  const child = spawn(executable, args, { cwd: rootDir, stdio: "inherit" });
  child.on("error", (error) => {
    console.error(error.message);
    process.exit(1);
  });
  child.on("exit", (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    else process.exit(code ?? 1);
  });
  return child;
}
