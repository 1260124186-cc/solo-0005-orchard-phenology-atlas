#!/usr/bin/env node
/** API 契约检查：真实后端 + 临时数据目录，覆盖健康、字典、错误包络与并发语义。 */

import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import {
  API_HOST,
  assertPortFree,
  createGuard,
  hasFlag,
  makeLogDir,
  makeRuntimeDir,
  removeDirQuietly,
  resolvePort,
  resolveTimeout,
  startProcess,
  valueAfter,
  waitForUrl,
} from "./lib/check_runtime.mjs";

const API_PORT = resolvePort("--api-port", "ORCHARD_CHECK_API_PORT", 8765);
const TIMEOUT_MS = resolveTimeout("--timeout-ms", "ORCHARD_CHECK_TIMEOUT_MS", 120_000);
const KEEP_LOGS = hasFlag("--keep-logs");
const API_ORIGIN = `http://${API_HOST}:${API_PORT}`;

const EXPECTED_STAGES = [
  "bud_swell",
  "bud_burst",
  "first_bloom",
  "full_bloom",
  "petal_fall",
  "fruit_set",
  "fruit_growth",
  "harvest",
  "leaf_fall",
];

const logDir = valueAfter("--log-dir") || makeLogDir("api");
mkdirSync(logDir, { recursive: true });
const runtimeDir = makeRuntimeDir();
const guard = createGuard({ timeoutMs: TIMEOUT_MS, scope: "api", logDir });
guard.state.dirs.push(runtimeDir);

let failed = null;
let assertions = 0;

try {
  await assertPortFree(API_PORT, API_HOST);
  const backend = startProcess(
    "python3",
    [
      "scripts/run_server.py",
      "--host",
      API_HOST,
      "--port",
      String(API_PORT),
      "--data-dir",
      runtimeDir,
    ],
    { logPath: join(logDir, "backend.log"), label: "backend" },
  );
  guard.state.processes.push(backend);
  await waitForUrl(`${API_ORIGIN}/api/health`, 20_000, () => backend.output);

  await runAssertions();

  console.log(`✅ API 检查通过（${assertions} 项断言）`);
} catch (error) {
  failed = error;
  console.error("❌ API 检查失败");
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode =
    error instanceof Error && error.message.includes("已被占用") ? 3 : 1;
} finally {
  await guard.cleanup();
  if (guard.state.watchdog) clearTimeout(guard.state.watchdog);
  if (failed) {
    console.error(`📁 失败日志保留在 ${logDir}`);
  } else if (!KEEP_LOGS) {
    removeDirQuietly(logDir);
  } else {
    console.log(`📁 检查日志保留在 ${logDir}`);
  }
}

function check(condition, message) {
  assertions += 1;
  if (!condition) {
    throw new Error(`断言失败：${message}`);
  }
}

async function runAssertions() {
  // 1. 健康与阶段字典
  const health = await api("/health");
  check(health.status === "ok", "健康检查应返回 status=ok");
  check(health.service === "orchard-phenology-atlas", "健康检查服务名不匹配");

  const stages = await api("/stages");
  check(stages.items.length === 9, "阶段字典应包含 9 个阶段");
  const keys = stages.items.map((item) => item.key);
  check(
    JSON.stringify(keys) === JSON.stringify(EXPECTED_STAGES),
    `阶段顺序不符合固定物候顺序：${keys.join(",")}`,
  );
  const required = stages.items
    .filter((item) => item.required_for_completion)
    .map((item) => item.key);
  check(
    JSON.stringify(required) ===
      JSON.stringify(["bud_burst", "full_bloom", "fruit_set", "harvest"]),
    "必需阶段集合不符合规则",
  );

  // 2. 统一错误包络
  const missing = await apiRaw("/no-such-route");
  check(missing.status === 404, "未知路由应返回 404");
  check(
    missing.payload?.error?.code === "not_found" &&
      typeof missing.payload.error.message === "string",
    "未知路由错误包络不符合约定",
  );

  const invalidPlot = await apiRaw("/plots", "PUT", { code: "bad code" });
  check(invalidPlot.status === 422, "非法园区载荷应返回 422");
  check(
    invalidPlot.payload?.error?.code === "validation_error",
    "非法载荷错误码应为 validation_error",
  );

  // 3. 园区生命周期与唯一性
  const plotBody = {
    code: "OR-9101",
    name: "API 检查梨园",
    locality: "检查用山谷",
    cultivar_focus: "检查梨",
    steward: "自动检查组",
    planting_year: 2015,
    note: "",
  };
  const plot = await api("/plots", "PUT", plotBody);
  check(plot.status === "draft" && plot.revision === 1, "新建园区应为草稿且修订号为 1");

  const duplicate = await apiRaw("/plots", "PUT", plotBody);
  check(duplicate.status === 409, "重复园区编号应返回 409");
  check(
    duplicate.payload?.error?.code === "plot_code_exists",
    "重复编号错误码应为 plot_code_exists",
  );

  const tree = await api("/trees", "PUT", {
    plot_id: plot.id,
    code: "OR-9101-T01",
    cultivar: "检查梨",
    rootstock: "杜梨",
    planting_year: 2015,
    status: "active",
    note: "",
  });
  check(tree.status === "active", "新建植株应为 active");

  // 4. 乐观并发：旧修订号必须冲突
  const stale = await apiRaw(`/plots/${plot.id}`, "PATCH", {
    name: "过期修订写入",
    revision: 99,
  });
  check(stale.status === 409, "过期修订号应返回 409");
  check(
    stale.payload?.error?.code === "revision_conflict",
    "过期修订错误码应为 revision_conflict",
  );

  const confirmed = await api(`/plots/${plot.id}/confirm`, "PUT", {
    revision: plot.revision,
  });
  check(confirmed.status === "confirmed", "园区确认后应为 confirmed");
  const reconfirm = await apiRaw(`/plots/${plot.id}/confirm`, "PUT", {
    revision: confirmed.revision,
  });
  check(reconfirm.status === 412, "重复确认应返回 412");
  check(
    reconfirm.payload?.error?.code === "plot_already_confirmed",
    "重复确认错误码应为 plot_already_confirmed",
  );

  // 5. 完成约束：缺必需阶段不得完成
  const observation = await api("/observations", "PUT", {
    tree_id: tree.id,
    season: "2026",
    observer: "API 检查组",
    note: "",
  });
  const earlyComplete = await apiRaw(
    `/observations/${observation.id}/complete`,
    "PUT",
    { revision: observation.revision },
  );
  check(earlyComplete.status === 412, "缺必需阶段完成应返回 412");
  check(
    earlyComplete.payload?.error?.code === "required_stages_missing",
    "缺阶段错误码应为 required_stages_missing",
  );

  // 6. 快照落盘：临时数据目录中应出现 state.json
  check(
    existsSync(join(runtimeDir, "state.json")),
    "写入后临时数据目录应存在 state.json 快照",
  );

  console.error(`  … 共 ${assertions} 项断言通过`);
}

async function api(path, method = "GET", body) {
  const { status, payload } = await apiRaw(path, method, body);
  if (status >= 400) {
    throw new Error(
      `API ${method} ${path} 意外失败（${status}）：${payload?.error?.message ?? "无错误信息"}`,
    );
  }
  return payload;
}

async function apiRaw(path, method = "GET", body) {
  const response = await fetch(`${API_ORIGIN}/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json().catch(() => null);
  return { status: response.status, payload };
}
