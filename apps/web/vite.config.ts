import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Local, dependency-free view of the build-time environment. The dev/prod
// proxy target defaults to the standard local API but can be overridden so the
// Playwright harness can point at an isolated E2E backend.
declare const process: { env: Record<string, string | undefined> };

const proxyTarget = process.env.TRACEMAP_PROXY_TARGET || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': proxyTarget, '/health': proxyTarget },
  },
  build: { outDir: 'dist' },
});
