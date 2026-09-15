#!/usr/bin/env node
/** 浏览器/API 检查共享运行时：进程组、端口、日志与回收。 */

import { spawn } from "node:child_process";
import {
  appendFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";

export const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../..");
export const API_HOST = "127.0.0.1";
export const UI_HOST = "127.0.0.1";

/** 解析 --flag value 形式的命令行参数。 */
export function valueAfter(flag, fallback = "") {
  const index = process.argv.indexOf(flag);
  if (index >= 0 && index + 1 < process.argv.length) {
    return process.argv[index + 1];
  }
  return fallback;
}

export function hasFlag(flag) {
  return process.argv.includes(flag);
}

/** 解析端口：命令行优先，其次环境变量，最后默认值。 */
export function resolvePort(flag, envName, fallback) {
  const raw = valueAfter(flag, process.env[envName] ?? "");
  if (!raw) return fallback;
  const port = Number.parseInt(raw, 10);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`端口无效（${flag}/${envName}）：${raw}`);
  }
  return port;
}

/** 解析超时毫秒数。 */
export function resolveTimeout(flag, envName, fallback) {
  const raw = valueAfter(flag, process.env[envName] ?? "");
  if (!raw) return fallback;
  const ms = Number.parseInt(raw, 10);
  if (!Number.isInteger(ms) || ms < 1000) {
    throw new Error(`超时设置无效（${flag}/${envName}）：${raw}`);
  }
  return ms;
}

/** 创建本次检查的日志目录，返回路径。 */
export function makeLogDir(scope) {
  const stamp = new Date()
    .toISOString()
    .replace(/[-:T]/g, "")
    .replace(/\..+$/, "");
  const dir = join(
    ROOT,
    "var",
    "check-runs",
    `${stamp}-${scope}-${process.pid}`,
  );
  mkdirSync(dir, { recursive: true });
  return dir;
}

/** 创建临时数据目录（快照与进程锁），进程退出时兜底清理。 */
export function makeRuntimeDir() {
  const dir = mkdtempSync(join(tmpdir(), "orchard-atlas-check-"));
  return dir;
}

export function removeDirQuietly(dir) {
  if (!dir) return;
  try {
    rmSync(dir, { recursive: true, force: true });
  } catch {
    // 清理失败不掩盖主结果
  }
}

/** 预检端口是否空闲；被占用时抛出带定位信息的错误。 */
export function assertPortFree(port, host = "127.0.0.1") {
  return new Promise((resolvePromise, rejectPromise) => {
    const probe = net.createServer();
    probe.once("error", (error) => {
      rejectPromise(
        new Error(
          `端口 ${host}:${port} 已被占用，无法启动检查服务。` +
            `请释放该端口，或通过 --*-port 指定其他端口。（${error.code ?? error.message}）`,
        ),
      );
    });
    probe.once("listening", () => {
      probe.close(() => resolvePromise());
    });
    probe.listen(port, host);
  });
}

/**
 * 以独立进程组启动子进程，stdout/stderr 同步追加到日志文件并保留在内存。
 * detached 使子进程成为进程组组长，便于整组回收（含 npm/vite 孙进程）。
 */
export function startProcess(command, args, { logPath, env = {}, label }) {
  const child = spawn(command, args, {
    cwd: ROOT,
    env: { ...process.env, CI: "1", ...env },
    stdio: ["ignore", "pipe", "pipe"],
    detached: process.platform !== "win32",
  });
  child.output = "";
  child.label = label ?? command;
  const record = (chunk) => {
    const text = chunk.toString();
    child.output += text;
    if (logPath) {
      try {
        appendFileSync(logPath, text);
      } catch {
        // 日志写入失败不中断检查
      }
    }
  };
  child.stdout.on("data", record);
  child.stderr.on("data", record);
  child.on("error", (error) => {
    record(`\n[启动失败] ${error.message}\n`);
  });
  return child;
}

function signalTree(child, signal) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  try {
    if (process.platform !== "win32") {
      // 负 PID 命中整个进程组，回收 vite/esbuild 等孙进程
      process.kill(-child.pid, signal);
    } else {
      child.kill(signal);
    }
  } catch {
    try {
      child.kill(signal);
    } catch {
      // 进程已退出
    }
  }
}

/** 先 SIGTERM 整组，超时后 SIGKILL 整组，确保无子进程残留。 */
export async function stopProcessTree(child, graceMs = 2500) {
  if (!child || (child.exitCode !== null || child.signalCode !== null)) return;
  signalTree(child, "SIGTERM");
  const exited = await Promise.race([
    new Promise((resolveExit) => child.once("exit", () => resolveExit(true))),
    new Promise((resolveTimeout) =>
      setTimeout(() => resolveTimeout(false), graceMs),
    ),
  ]);
  if (!exited) {
    signalTree(child, "SIGKILL");
    await Promise.race([
      new Promise((resolveExit) => child.once("exit", () => resolveExit(true))),
      new Promise((resolveTimeout) =>
        setTimeout(() => resolveTimeout(false), 1500),
      ),
    ]);
    console.error(`⚠️  进程 ${child.label ?? child.pid} 未及时退出，已强制结束。`);
  }
}

/** 轮询等待 URL 可访问。 */
export async function waitForUrl(url, timeoutMs, outputOf) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 180));
  }
  const details = typeof outputOf === "function" ? outputOf() : "";
  throw new Error(
    `等待 ${url} 超时（${timeoutMs}ms）：` +
      (lastError ? lastError.message : "无响应") +
      (details ? `\n--- 进程输出 ---\n${details.slice(-4000)}` : ""),
  );
}

/**
 * 检查生命周期守卫：统一处理超时、中断信号与资源回收。
 * resources: { browsers: [], processes: [], dirs: [] }
 * 清理进行中再次收到信号时立即强制退出，作为逃生通道。
 */
export function createGuard({ timeoutMs, scope, logDir }) {
  const state = {
    settled: false,
    cleaning: false,
    browsers: [],
    processes: [],
    dirs: [],
    watchdog: null,
  };

  async function cleanup() {
    for (const browser of state.browsers.splice(0)) {
      await browser.close().catch(() => undefined);
    }
    // 先全部发 SIGTERM，再统一等待，缩短回收时间
    const children = state.processes.splice(0);
    await Promise.all(children.map((child) => stopProcessTree(child)));
    for (const dir of state.dirs.splice(0)) {
      removeDirQuietly(dir);
    }
  }

  async function shutdown(code, message) {
    if (state.settled) {
      // 清理期间再次收到信号：放弃等待，立即退出
      if (state.cleaning) process.exit(code);
      return;
    }
    state.settled = true;
    state.cleaning = true;
    if (state.watchdog) clearTimeout(state.watchdog);
    if (message) {
      const line = `\n❌ ${scope}：${message}\n`;
      console.error(line.trim());
      if (logDir) {
        try {
          appendFileSync(join(logDir, "check.log"), line);
        } catch {
          // 忽略
        }
      }
    }
    await cleanup();
    state.cleaning = false;
    process.exit(code);
  }

  state.watchdog = setTimeout(() => {
    void shutdown(1, `整体超时（${timeoutMs}ms），已回收全部子进程`);
  }, timeoutMs);
  state.watchdog.unref?.();

  process.on("SIGINT", () => void shutdown(130, "收到中断信号（SIGINT）"));
  process.on("SIGTERM", () => void shutdown(143, "收到终止信号（SIGTERM）"));

  return { state, cleanup, shutdown };
}
