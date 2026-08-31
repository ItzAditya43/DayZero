import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// In production FastAPI serves dist/ from the same origin, so there is no
// proxy and no CORS. This proxy exists only for `npm run dev`.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  // The MapLibre worker is an ES module; emitting workers as ESM keeps its
  // internal imports intact.
  worker: { format: "es" },
  build: { outDir: "dist", chunkSizeWarningLimit: 1600 },
});
