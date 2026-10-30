import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev origin (127.0.0.1:5173) is allowlisted by the backend in development
// mode; the Vite dev server proxies /api to the backend, so the browser
// session cookie stays same-origin and CORS is never exercised. Set
// OBSERVATORY_PORT dev-side too when the backend does not run on 8000.
const backendPort = process.env.OBSERVATORY_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${backendPort}`,
        ws: true,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    globals: false,
    css: false,
  },
});
