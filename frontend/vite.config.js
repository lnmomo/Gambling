import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import {fileURLToPath} from "node:url";

export default defineConfig(({command}) => ({
  plugins: [react()],
  base: command === "serve" ? "/" : "/static/",
  server: {proxy: {"/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000"}},
  build: {
    outDir: fileURLToPath(new URL("../football_agents/web", import.meta.url)),
    emptyOutDir: true,
    rollupOptions: {output: {entryFileNames: "app.js", chunkFileNames: "chunk-[name].js", assetFileNames: asset => asset.name?.endsWith(".css") ? "styles.css" : "[name][extname]"}},
  },
}));
