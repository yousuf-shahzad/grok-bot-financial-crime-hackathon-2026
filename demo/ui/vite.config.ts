import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into demo/ui/dist and served by demo/app.py; `npm run dev` proxies the API to it.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 1500 },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
