import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
export default defineConfig({
    plugins: [react()],
    base: "/static/",
    build: {
        outDir: resolve(__dirname, "../football_agents/web"),
        emptyOutDir: true,
        rollupOptions: {
            output: {
                entryFileNames: "app.js",
                chunkFileNames: "chunk-[name].js",
                assetFileNames: asset => asset.name?.endsWith(".css") ? "styles.css" : "[name][extname]"
            }
        }
    }
});
