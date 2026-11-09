import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  use: { ...devices['Desktop Chrome'], baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' },
  webServer: [
    {command: 'bash -lc "cd ../api && TRACEMAP_ENV=development TRACEMAP_DATABASE_URL=sqlite:////tmp/tracemap-e2e.db uvicorn tracemap.main:app --host 127.0.0.1 --port 8000"',
      url: 'http://127.0.0.1:8000/health', reuseExistingServer: !process.env.CI, timeout: 90000},
    {command: 'npm run dev', url: 'http://127.0.0.1:5173', reuseExistingServer: !process.env.CI, timeout: 90000}
  ]
});
