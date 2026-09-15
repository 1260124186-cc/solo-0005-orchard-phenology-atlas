/**
 * Vitest 全局测试环境准备。
 *
 * 组件通过 services/api.ts 读取 localStorage 中的 actor，并为写请求生成
 * 幂等键（crypto.randomUUID）。jsdom 提供了 localStorage；randomUUID 由
 * Node 运行时注入，缺失时使用确定性回退，保证旧环境也能跑测试。
 */

if (!globalThis.localStorage) {
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, String(value)),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    },
    configurable: true,
  });
}

if (!globalThis.crypto?.randomUUID) {
  Object.defineProperty(globalThis, "crypto", {
    value: {
      ...(globalThis.crypto ?? {}),
      randomUUID: () =>
        `test-uuid-${Math.random().toString(16).slice(2)}-${Date.now()}`,
    },
    configurable: true,
  });
}

if (!globalThis.localStorage.getItem("orchardAtlasActor")) {
  globalThis.localStorage.setItem("orchardAtlasActor", "local-admin");
}
