#!/usr/bin/env node
/**
 * 本地统一验证入口：按确定顺序执行
 *   环境预检 → 仓库卫生 → 依赖安装 → Playwright 浏览器 →
 *   类型检查 → 生产构建 → Python 编译 → API 检查 → 三条浏览器工作流
 * 任一步骤失败立即停止，保留可定位日志并返回非零状态。
 */

import { execFile } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { promisify } from "node:util";
import {
  ROOT,
  hasFlag,
  removeDirQuietly,
  resolvePort,
  startProcess,
  stopProcessTree,
  valueAfter,
} from "./lib/check_runtime.mjs";

const execFileAsync = promisify(execFile);

const API_PORT = resolvePort("--api-port", "ORCHARD_VERIFY_API_PORT", 8765);
const UI_PORT = resolvePort("--ui-port", "ORCHARD_VERIFY_UI_PORT", 4317);
const KEEP_LOGS = hasFlag("--keep-logs");
const WITH_DEPS = hasFlag("--with-deps");

const stamp = new Date().toISOString().replace(/[-:T]/g, "").replace(/\..+$/, "");
const runDir = join(ROOT, "var", "verify", `${stamp}-${process.pid}`);
mkdirSync(runDir, { recursive: true });

const results = [];
let currentChild = null;
let interrupted = false;

async function shutdownOnSignal(signalName, code) {
  if (interrupted) return;
  interrupted = true;
  console.error(`\n⚠️  收到 ${signalName}，正在回收当前步骤子进程…`);
  if (currentChild) await stopProcessTree(currentChild);
  console.error(`📁 中断前日志保留在 ${runDir}`);
  process.exit(code);
}
process.on("SIGINT", () => void shutdownOnSignal("SIGINT", 130));
process.on("SIGTERM", () => void shutdownOnSignal("SIGTERM", 143));

/** 运行一个子进程步骤：输出同时写入终端与步骤日志。 */
function runCommand(name, command, args, { timeoutMs, env = {} } = {}) {
  return new Promise((resolveStep) => {
    const logPath = join(runDir, `${logName(name)}.log`);
    appendFileSync(logPath, `$ ${command} ${args.join(" ")}\n\n`);
    const child = startProcess(command, args, { logPath, env, label: name });
    currentChild = child;
    const tee = (chunk) => process.stdout.write(chunk);
    child.stdout.on("data", tee);
    child.stderr.on("data", tee);
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      void stopProcessTree(child);
    }, timeoutMs);
    child.on("exit", (code, signal) => {
      clearTimeout(timer);
      currentChild = null;
      if (interrupted) {
        resolveStep({ ok: false, logPath, note: "被中断" });
        return;
      }
      if (timedOut) {
        resolveStep({ ok: false, logPath, note: `超过 ${timeoutMs}ms 上限` });
        return;
      }
      if (code === 0) {
        resolveStep({ ok: true, logPath });
      } else {
        resolveStep({
          ok: false,
          logPath,
          note: `退出码 ${code ?? signal}`,
        });
      }
    });
  });
}

function logName(name) {
  return name.replace(/[^a-z0-9-]+/gi, "-").toLowerCase();
}

async function preflight() {
  const checks = [
    ["node", ["--version"], 20, "Node.js"],
    ["npm", ["--version"], 10, "npm"],
    ["python3", ["--version"], null, "Python"],
    ["git", ["--version"], null, "git"],
  ];
  for (const [cmd, args, minMajor, label] of checks) {
    const { stdout } = await execFileAsync(cmd, args);
    const version = stdout.trim();
    console.log(`  ${label}: ${version}`);
    if (minMajor !== null) {
      const major = Number.parseInt(version.replace(/^[^\d]*/, ""), 10);
      if (!Number.isInteger(major) || major < minMajor) {
        throw new Error(`${label} 版本过低：${version}（需要 >= ${minMajor}）`);
      }
    }
  }
  const pythonVersion = (
    await execFileAsync("python3", [
      "-c",
      "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
    ])
  ).stdout.trim();
  const [pyMajor, pyMinor] = pythonVersion.split(".").map(Number);
  if (pyMajor < 3 || (pyMajor === 3 && pyMinor < 11)) {
    throw new Error(`Python 版本过低：${pythonVersion}（需要 >= 3.11）`);
  }
}

async function ensurePlaywright() {
  const { chromium } = await import("playwright");
  const executable = chromium.executablePath();
  if (existsSync(executable) && !WITH_DEPS) {
    console.log(`  Chromium 已就绪：${executable}`);
    return;
  }
  const args = [
    join(ROOT, "node_modules", "playwright", "cli.js"),
    "install",
    ...(WITH_DEPS ? ["--with-deps"] : []),
    "chromium",
  ];
  const result = await runCommand("playwright-install", process.execPath, args, {
    timeoutMs: 600_000,
  });
  if (!result.ok) {
    throw new Error(`Playwright Chromium 准备失败（日志 ${result.logPath}）`);
  }
  if (!existsSync(chromium.executablePath())) {
    throw new Error("Playwright Chromium 安装后仍不可执行");
  }
}

const WORKFLOWS = ["catalog", "observe", "compare"];

function buildSteps() {
  const npmCmd = process.platform === "win32" ? "npm.cmd" : "npm";
  const installArgs = existsSync(join(ROOT, "package-lock.json"))
    ? ["ci", "--no-audit", "--no-fund"]
    : ["install", "--no-audit", "--no-fund"];
  return [
    {
      name: "01-环境预检",
            run: () =>
        preflight().then(
          () => ({ ok: true }),
          (error) => ({ ok: false, note: error.message }),
        ),
    },
    {
      name: "02-仓库卫生",
            run: () =>
        runCommand("02-仓库卫生", process.execPath, ["scripts/check_hygiene.mjs"], {
          timeoutMs: 60_000,
        }),
    },
    {
      name: "03-依赖安装",
            run: () => runCommand("03-依赖安装", npmCmd, installArgs, { timeoutMs: 600_000 }),
    },
    {
      name: "04-Playwright浏览器",
            run: () =>
        ensurePlaywright().then(
          () => ({ ok: true }),
          (error) => ({ ok: false, note: error.message }),
        ),
    },
    {
      name: "05-类型检查",
            run: () =>
        runCommand(
          "05-类型检查",
          process.execPath,
          [join("node_modules", "vue-tsc", "bin", "vue-tsc.js"), "--noEmit"],
          { timeoutMs: 300_000 },
        ),
    },
    {
      name: "06-生产构建",
            run: () => runCommand("06-生产构建", npmCmd, ["run", "build"], { timeoutMs: 300_000 }),
    },
    {
      name: "07-Python编译",
            run: () =>
        runCommand(
          "07-Python编译",
          "python3",
          ["-m", "compileall", "-q", "backend", "scripts"],
          { timeoutMs: 120_000 },
        ),
    },
    {
      name: "08-API检查",
            run: () =>
        runCommand(
          "08-API检查",
          process.execPath,
          [
            "scripts/api_check.mjs",
            "--api-port",
            String(API_PORT),
            "--log-dir",
            join(runDir, "api"),
            ...(KEEP_LOGS ? ["--keep-logs"] : []),
          ],
          { timeoutMs: 180_000 },
        ),
    },
    ...WORKFLOWS.map((workflow, index) => ({
      name: `${String(index + 9).padStart(2, "0")}-工作流-${workflow}`,
            run: () =>
        runCommand(
          `workflow-${workflow}`,
          process.execPath,
          [
            "scripts/workflow_check.mjs",
            "--workflow",
            workflow,
            "--api-port",
            String(API_PORT),
            "--ui-port",
            String(UI_PORT),
            "--log-dir",
            join(runDir, `workflow-${workflow}`),
            ...(KEEP_LOGS ? ["--keep-logs"] : []),
          ],
          { timeoutMs: 240_000 },
        ),
    })),
  ];
}

function formatDuration(ms) {
  return ms >= 60_000
    ? `${(ms / 60_000).toFixed(1)}min`
    : `${(ms / 1000).toFixed(1)}s`;
}

console.log(`🧭 统一验证开始，日志目录 ${runDir}`);
console.log(`   API 端口 ${API_PORT}，UI 端口 ${UI_PORT}`);
const startedAt = Date.now();
let failure = null;

for (const step of buildSteps()) {
  const stepStart = Date.now();
  console.log(`\n▶ ${step.name}`);
  const result = await step.run();
  const duration = Date.now() - stepStart;
  if (result.ok) {
    results.push({ name: step.name, status: "通过", duration });
    console.log(`✔ ${step.name}（${formatDuration(duration)}）`);
  } else {
    results.push({ name: step.name, status: "失败", duration });
    failure = { step, result };
    console.error(`\n✘ ${step.name} 失败${result.note ? `：${result.note}` : ""}`);
    if (result.logPath) console.error(`📁 步骤日志：${result.logPath}`);
    break;
  }
  if (interrupted) break;
}

const total = Date.now() - startedAt;
console.log("\n──────── 验证摘要 ────────");
for (const item of results) {
  console.log(
    `${item.status === "通过" ? "✅" : "❌"} ${item.name}  ${formatDuration(item.duration)}`,
  );
}
console.log(`总耗时：${formatDuration(total)}`);

if (failure || interrupted) {
  console.error(`\n❌ 统一验证失败，已保留日志目录 ${runDir}`);
  process.exit(1);
}
if (!KEEP_LOGS) {
  removeDirQuietly(runDir);
} else {
  console.log(`📁 日志保留在 ${runDir}`);
}
console.log("✅ 统一验证全部通过");
