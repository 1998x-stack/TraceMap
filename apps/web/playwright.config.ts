import { defineConfig, devices } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// End-to-end runs must never touch the developer's dev database or dev servers.
// We therefore (a) resolve the backend interpreter from the project virtualenv
// instead of assuming a global `uvicorn`/`python`, and (b) bind the E2E API and
// web servers to dedicated ports with a throwaway SQLite file.
const apiDir = path.resolve(process.cwd(), '..', 'api');
const venvPython = path.join(apiDir, '.venv', 'bin', 'python');
const apiPython = process.env.TRACEMAP_API_PYTHON
  ?? (fs.existsSync(venvPython) ? venvPython : 'python3');
const apiPort = process.env.TRACEMAP_E2E_API_PORT ?? '8010';
const webPort = process.env.TRACEMAP_E2E_WEB_PORT ?? '5273';
const e2eDatabaseUrl = process.env.TRACEMAP_E2E_DATABASE_URL
  ?? `sqlite:///${path.join(os.tmpdir(), `tracemap-e2e-${process.pid}-${Date.now()}.db`)}`;

export default defineConfig({
  testDir: './e2e',
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${webPort}`, trace: 'retain-on-failure' },
  webServer: [
    {
      command: `${JSON.stringify(apiPython)} -m uvicorn tracemap.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: apiDir,
      env: { TRACEMAP_ENV: 'development', TRACEMAP_DATABASE_URL: e2eDatabaseUrl },
      url: `http://127.0.0.1:${apiPort}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 90000,
    },
    {
      command: `npm run dev -- --port ${webPort} --strictPort`,
      env: { TRACEMAP_PROXY_TARGET: `http://127.0.0.1:${apiPort}` },
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: !process.env.CI,
      timeout: 90000,
    },
  ],
});
