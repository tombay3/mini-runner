import path from "node:path";
import { launchPython, rootDir } from "./launch-python.mjs";

launchPython([path.join(rootDir, "app.py"), ...process.argv.slice(2)],
  "Create .venv and install requirements.txt before running npm run api.");
