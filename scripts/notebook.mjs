import { launchPython, rootDir } from "./launch-python.mjs";

launchPython([
  "-m", "notebook",
  "--no-browser",
  "--ip=0.0.0.0",
  "--port=8081",
  "--ServerApp.port_retries=0",
  `--ServerApp.root_dir=${rootDir}`,
  "--JupyterNotebookApp.default_url=/tree/analytics",
  "--IdentityProvider.token=",
  "--PasswordIdentityProvider.hashed_password=",
  ...process.argv.slice(2),
], "Create .venv and install Jupyter Notebook before running npm run notebook.");
