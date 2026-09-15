# 测试发现的实现矛盾

本文件记录验证套件暴露、但**未通过修改断言去迎合**的实现问题。每个条目包含：
最小复现、实际结果、预期来源。对应测试用 `@unittest.expectedFailure`
（后端）显式标记，修复实现后移除装饰器即可让断言守护回归。

## F-001：重复编号冲突抛 TypeError，HTTP 退化为 500 而不是稳定的 409

- 状态：未修复（基线实现）
- 涉及代码：
  - `backend/app/domain/plot_rules.py` `ensure_unique_plot_code()`
  - `backend/app/domain/plot_rules.py` `ensure_unique_tree_code()`

### 预期来源

- `PROJECT_SPEC.md`「三条连通工作流 / 园区与植株编目」：
  > 服务端同时检查园区编号唯一性、植株编号唯一性……任何失败返回稳定错误码，且不写入部分数据。
- `PROJECT_SPEC.md`「接口约定」：
  > 错误响应统一为 `{ "error": { "code", "message", "details" } }`。
- `README.md`「数据与一致性」：
  > 同一园区内植株编号唯一。
- 领域代码中已定义的错误码字符串本身就是预期契约：
  `plot_code_exists`（409 `ConflictError`）与 `tree_code_exists`（409）。

### 最小复现

```python
from app.errors import ConflictError

# plot_rules.py:91-97 / 241-251 的实际构造方式：
raise ConflictError(
    "tree_code_exists",      # 位置参数 -> 绑定到 __init__ 的 code 形参
    "该园区内植株编号已存在",
    code=code,               # 关键字参数 -> 再次给 code 赋值
)
```

`ConflictError.__init__(self, code: str, message: str, **details)` 同时通过
位置参数和关键字 `code=` 接收错误码，Python 直接抛出：

```
TypeError: ConflictError.__init__() got multiple values for argument 'code'
```

经 HTTP 层时，`TypeError` 不匹配任何 `DomainError`，被统一异常处理转成：

```
HTTP 500
{ "error": { "code": "internal_error",
             "message": "服务处理请求时发生未知错误",
             "details": { "type": "TypeError" } } }
```

### 触发路径（任一即可）

1. 同一园区内创建两株编号相同的植株（`PUT /api/trees`，第二次请求）。
2. 创建两个 `code` 相同的园区（`PUT /api/plots`，第二次请求）。
3. 两个完全相同的“建园”请求并发提交时，事务串行化后落败的一方必然走到
   `ensure_unique_plot_code`，同样触发 500。

### 实际结果

- 调用方拿到 `500 internal_error`，无法据此区分“编号冲突”与真实服务故障，
  前端只会显示“服务处理请求时发生未知错误”，不会提示修改编号。
- 事务本身行为正确：异常发生在提交前，`BEGIN IMMEDIATE` 事务回滚，
  **不会写入部分数据**（这一点由测试单独断言守护）。
- 并发相同建园：恰好一条事实落库，另一条返回 500（应返回 409）。

### 建议修复（实现层，不在本测试任务内改动）

将两处 `code=code`（以及 `plot_code_exists` 调用点同样的写法）改为放入
`details`，例如：

```python
raise ConflictError("tree_code_exists", "该园区内植株编号已存在", duplicate_code=code)
```

或直接去掉重复的关键字参数。修复后：

1. 移除 `backend/tests/test_catalog_rules.py`
   `test_tree_code_must_be_unique_within_its_plot_but_not_across_plots`
   上的 `@unittest.expectedFailure`；
2. 移除 `backend/tests/test_http_business.py`
   `test_duplicate_tree_code_returns_409_not_500` 与
   `test_concurrent_identical_creates_yield_single_fact` 上的
   `@unittest.expectedFailure`；
3. `npm run test:backend` 中三条 `expected failures` 应归零。

### 覆盖该问题的测试

- `backend/tests/test_catalog_rules.py::TreeOwnershipTests::test_tree_code_must_be_unique_within_its_plot_but_not_across_plots`
- `backend/tests/test_http_business.py::HttpBusinessTestCase::test_duplicate_tree_code_returns_409_not_500`
- `backend/tests/test_http_business.py::HttpBusinessTestCase::test_concurrent_identical_creates_yield_single_fact`

## F-002：浏览器检查终止时 vite/esbuild 被孤立，串行执行 `npm run check` 挂死（已修复）

- 状态：**已在 `scripts/workflow_check.mjs` 中修复**（测试基础设施，不改产品代码）。
- 现象：`startProcess("npm", ["run","dev", ...])` 实际派生 `npm → sh -c vite →
  vite → esbuild`；旧版 `stopProcess` 只对最外层 npm 进程发 SIGTERM，npm 退出后
  vite/esbuild 被 init 收养（ppid=1），继续监听固定端口 4317。单独运行某一条
  工作流时影响不明显（脚本随之退出），但 `npm run check` 串行执行三条工作流时，
  下一条的 `waitForUrl(http://127.0.0.1:4317/)` 可能连到旧实例，且端口状态混乱，
  整条命令长时间不退出。
- 修复：派生子进程时使用独立进程组（`detached: true`），结束时对整个进程组
  发 SIGTERM，超时再对整组 SIGKILL，确保 vite 与 esbuild 一并退出。
- 验证：`npm run check` 从干净状态一次跑完构建、编译、54 个后端测试、
  16 个前端测试与三条浏览器工作流，退出码 0，无残留进程。
