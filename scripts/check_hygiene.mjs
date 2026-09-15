#!/usr/bin/env node
/**
 * 仓库卫生门禁：阻止运行快照、构建产物、浏览器缓存和临时证据进入提交。
 * 检查 git 索引（已跟踪 + 已暂存），命中即失败并列出全部违规路径。
 */

import { execFileSync } from "node:child_process";

const FORBIDDEN = [
  { pattern: /(^|\/)dist\//, label: "前端构建产物" },
  { pattern: /(^|\/)backend\/var\//, label: "后端运行快照目录" },
  { pattern: /(^|\/)var\/(check-runs|verify)\//, label: "检查临时证据" },
  { pattern: /(^|\/)node_modules\//, label: "依赖目录" },
  { pattern: /(^|\/)__pycache__\//, label: "Python 字节码缓存" },
  { pattern: /\.py[co]$/, label: "Python 字节码" },
  { pattern: /(^|\/)playwright-report\//, label: "Playwright 报告缓存" },
  { pattern: /(^|\/)test-results\//, label: "测试临时产物" },
  { pattern: /(^|\/)\.vite\//, label: "Vite 缓存" },
  { pattern: /(^|\/)ms-playwright/, label: "Playwright 浏览器缓存" },
  { pattern: /(^|\/)state\.json$/, label: "运行状态快照" },
  { pattern: /(^|\/)repository\.lock$/, label: "仓储进程锁" },
  { pattern: /\.log$/, label: "日志文件" },
];

function listIndexFiles() {
  try {
    const output = execFileSync("git", ["ls-files", "-z"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    return output.split("\0").filter(Boolean);
  } catch (error) {
    console.error("❌ 无法读取 git 索引，卫生检查中止");
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(2);
  }
}

const files = listIndexFiles();
const offenders = [];
for (const file of files) {
  for (const { pattern, label } of FORBIDDEN) {
    if (pattern.test(file)) {
      offenders.push({ file, label });
      break;
    }
  }
}

if (offenders.length > 0) {
  console.error("❌ 仓库卫生检查失败：以下路径不应进入提交");
  for (const { file, label } of offenders) {
    console.error(`  - ${file}（${label}）`);
  }
  console.error("请将其移出 git 索引（git rm --cached）并确认 .gitignore 覆盖。");
  process.exit(1);
}

console.log(`✅ 仓库卫生检查通过（索引共 ${files.length} 个文件）`);
