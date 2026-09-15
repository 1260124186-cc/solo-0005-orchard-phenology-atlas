import { defineConfig } from "vitest/config";
import vue from "@vitejs/plugin-vue";

// 测试沿用生产的 Vite + @vitejs/plugin-vue 管线，仅切换 root 到 frontend
// （与 vite.config.ts 一致），并使用 jsdom 承载真实组件渲染。
export default defineConfig({
  root: "frontend",
  plugins: [vue()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/testing/setup.ts"],
    include: ["../frontend/src/**/*.spec.ts"],
    css: false,
    restoreMocks: true,
  },
});
