import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    ...(process.env.HARBORSHIFT_BROWSER_CHANNEL ? { channel: process.env.HARBORSHIFT_BROWSER_CHANNEL } : {}),
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: [
    { command: 'python -m uvicorn api.main:app --host 127.0.0.1 --port 8000', cwd: '..', url: 'http://127.0.0.1:8000/health', reuseExistingServer: false },
    { command: 'npm run dev -- --port 5173 --strictPort', url: 'http://127.0.0.1:5173', reuseExistingServer: false },
  ],
});
