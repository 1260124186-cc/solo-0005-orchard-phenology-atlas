import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 浏览器检查可用 ORCHARD_ATLAS_PORT 指定后端端口，避免并行任务互相污染。
const apiPort = process.env.ORCHARD_ATLAS_PORT ?? "8765";
const apiTarget = `http://127.0.0.1:${apiPort}`;

export default defineConfig({
  root: "frontend",
  plugins: [vue()],
  server: {
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
  preview: {
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
