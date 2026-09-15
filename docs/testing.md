# 业务回归验证

本目录之外新增的验证面向**业务规则回归**，而不是当前输出的快照。预期全部来自
`PROJECT_SPEC.md` 与 `README.md` 中写明的约束；当测试暴露实现矛盾时，在
[`docs/test-findings.md`](test-findings.md) 记录最小复现、实际结果与预期来源，
不用修改断言去迎合实现。

## 从干净环境执行

```bash
# 1. 安装依赖（Node 20+ / npm 10+ / Python 3.11+）
npm install
npx playwright install chromium   # 仅浏览器工作流检查需要

# 精简容器中若 Chromium 报 libnspr4.so / libnss3.so 等缺失，
# 还需安装 Playwright 的系统依赖（Debian/Ubuntu）：
sudo npx playwright install-deps chromium
# 无 root 时也可从发行版仓库下载对应 .deb 解包到用户目录，
# 并通过 LD_LIBRARY_PATH 提供给 chrome-headless-shell。

# 2. 后端：真实 SQLite + 真实 HTTP 服务（临时数据目录）
npm run test:backend

# 3. 前端：Vue Test Utils + Vitest（jsdom），组件挂载 + 真实 api 客户端
npm run test:frontend

# 4. 生产构建、Python 编译、前后端测试、三条真实浏览器工作流
npm run check
```

所有测试不访问互联网，数据库均落在系统临时目录并在用例结束后清理。

## 后端测试（unittest，标准库 + 真实 HTTP 层）

文件位于 `backend/tests/`：

| 文件 | 覆盖的业务规则 |
| --- | --- |
| `test_catalog_rules.py` | 园区确认的父子约束（至少一株 active 植株；退休植株不算数）、确认后冻结、重复确认、植株必须归属存在的园区、同园区编号唯一（跨园区可重复）、草稿园区才能加植株、定植年份不得早于园区起始年 |
| `test_observation_rules.py` | 阶段顺序（rank 与日期都不倒退）、四个必需阶段才能完成、可选阶段不能替代必需阶段、同阶段重复、季节观察窗口、完成后增删改一律拒绝、同植株同年唯一、退休植株不能建志 |
| `test_comparison_rules.py` | 同年比较、两侧必须 completed、无共同阶段拒绝（不补零不推断）、只用共同阶段计算“右侧−左侧”偏移、同一对重复生成不产生第二条事实、禁止自比较 |
| `test_transaction_adversary.py` | 乐观修订冲突 409 且不覆盖较新状态、同 revision 并发确认只允许一个赢家、幂等键复用不增加实体/审计、同键不同体 409、action 成功但关系检查失败时整笔回滚、COMMIT 落盘失败后再读仍是旧状态 |
| `test_http_business.py` | 启动与生产相同的标准库 HTTP 服务（临时数据目录、随机端口、真实 socket），验证全部上述规则的 **HTTP 状态码与稳定错误码**、成功结果在“重启仓储”后仍可从磁盘读回、并发 HTTP 请求只产生一条事实、鉴权 401/403 |

关键设计：

- HTTP 用例通过 `app.transport.server.create_server` 启动真实
  `ThreadingHTTPServer`，请求经由路由、JSON 解析、`X-Actor-Id` 授权、
  幂等中间件、事务、审计/outbox 全链路；不直接调用 handler。
- 持久化断言在写入后用**同一数据库文件新建第二个 `Repository`**（模拟进程重启），
  防止“只在内存里成立”。
- 落盘失败用例替换 `Database.transaction` 上下文管理器，在 COMMIT 点注入
  `sqlite3.OperationalError`（磁盘 I/O），随后按生产逻辑回滚并断言再次读取
  看不到“逻辑已写”的实体。
- 已知实现缺陷以 `@unittest.expectedFailure` 标记，见
  `docs/test-findings.md` F-001；套件输出会显示 `expected failures=N`。

## 前端测试（Vitest + @vue/test-utils + jsdom）

配置 `vitest.config.ts` 复用生产的 Vite + `@vitejs/plugin-vue` 管线。
测试**不只测纯函数**：每个用例都挂载真实组件/完整 App，组件通过
`services/api.ts` 的真实 HTTP 客户端发请求，fetch 被一个按后端真实契约工作的
内存假后端接管（`src/testing/fakeServer.ts`：真实错误信封、状态码、revision
乐观并发、幂等键、阶段顺序与必需阶段规则）。

| 文件 | 覆盖内容 |
| --- | --- |
| `components/ObservationStageForm.spec.ts` | 日期按天精度（恰好十位 `YYYY-MM-DD`，无时分秒）、日期倒退的页面反馈、缺日期不放行、已登记阶段在真实选择菜单中禁用 |
| `views/ObservationProgress.spec.ts` | 完成进度只统计四个必需阶段（0%→25%→…→100%）、可选阶段不提高进度但轨道标记已记录、完成后表单与移除按钮消失、状态印章切换 |
| `views/ComparisonAvailability.spec.ts` | 比较按钮可用条件（两份、同年、completed、有共同阶段、非自身）、年份不同/无共同阶段的禁用与提示、真实生成四条确定性偏移（+5/+4/+4/+5）、服务端提交点 412 时显示冲突反馈且不出现结果区 |
| `views/AdversarialFlows.spec.ts` | 三类对抗场景（见下） |

### 三类对抗场景

1. **同一操作并发提交**（`AdversarialFlows.spec.ts` A）：两个基于同一 revision
   的补录请求并发发出，服务端只接受一个，另一个收到 `revision_conflict` /
   `stage_exists`，服务端与页面都只有一条条目，失败通过全局 Toast 反馈。
2. **第一次写入业务成功但后续关系检查失败**（B）：建志成功后，第一次补录阶段
   在事务末尾的关系检查失败（注入 500 `state_relationships_invalid`），
   阶段不落库、页面不乐观保留、重新读取仍为空，并且可以再次补录成功。
3. **页面最新版本与接口重新读取不一致**（C）：另一标签页先把 revision 从 1
   推进到 2，旧页面仍持 revision=1 提交，必须收到“记录已被其他请求修改”的
   409 反馈且不覆盖新事实；重新读取后页面与服务端一致，再用新 revision
   提交成功。另含完成冻结后旧页面补录被 `season_not_editable` 拒绝的场景。

## 不做的事

- 不断言中文文案的逐字快照或不稳定的时间戳、ID；只断言业务含义、状态码、
  错误码、计数与确定性计算结果。
- 不修改产品代码去让测试通过；实现矛盾见 `docs/test-findings.md`。
