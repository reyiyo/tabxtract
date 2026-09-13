import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server exists only for Tauri's webview: it listens on localhost on
// a fixed port because tauri.conf.json points there (devUrl).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    target: "es2021",
    sourcemap: false,
  },
  test: {
    // Component tests render into a DOM; the pure tests do not mind it.
    environment: "jsdom",
    setupFiles: ["src/__tests__/setup.ts"],
  },
});
