import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['junit', { outputFile: 'test-results/webui.xml' }],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:8766',
    viewport: { width: 1280, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'python -m uvicorn tools.webui_e2e_server:app --host 127.0.0.1 --port 8766 --workers 1',
    cwd: '..',
    url: 'http://127.0.0.1:8766/health',
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
