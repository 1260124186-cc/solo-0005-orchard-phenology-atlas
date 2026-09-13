# 果园物候图谱编研台

面向地方品种保护人员、果园档案员和农业文化研究者的全栈编研工具。产品从园区建档开始，逐株登记果树，按季节记录物候阶段，再将两份已完成的季节志进行确定性对齐，并生成可长期保存的编研简报。

系统不连接外部气象、地图或数据库服务。档案保存在本机 JSON 快照中，便于离线查阅和后续迁移。

## 主要能力

- 园区档案：建立园区草稿，登记编号、地点、重点品种、责任人和种植年份。
- 植株编目：按园区维护植株编号、品种、砧木、定植年份和生长状态。
- 季节物候：按固定阶段顺序记录日期、置信度和说明，完成后冻结。
- 品种比较：只对两份同年已完成季节志的共同阶段计算日期偏移。
- 编研简报：冻结已确认园区在生成时点的植株与季节志摘要，并下载文本。

## 技术结构

```text
.
├── frontend/                 Vue 3 与 TypeScript 用户界面
│   └── src/
│       ├── app/              工作区状态与用例协调
│       ├── components/       表单、阶段轨道、植株卡片和反馈组件
│       ├── domain/           前端阶段字典、类型和边界规则
│       ├── services/         HTTP 调用与错误映射
│       └── views/            园区、观察、比较和简报工作面
├── backend/app/              Python 标准库服务
│   ├── application/          用例编排
│   ├── domain/               实体规则、状态转换和比较计算
│   ├── persistence/          进程锁、快照与原子落盘
│   └── transport/            HTTP 路由与响应编码
├── scripts/
│   ├── run_server.py         后端启动入口
│   └── workflow_check.mjs    三条浏览器工作流检查
├── PROJECT_SPEC.md
├── .project-manifest.json
└── .project-runtime.json
```

## 环境要求

- Node.js 20 或更高版本
- npm 10 或更高版本
- Python 3.11 或更高版本
- Playwright Chromium（浏览器工作流检查需要）

首次安装：

```bash
npm install
npx playwright install chromium
```

## 构建

```bash
npm run build
python3 -m compileall -q backend scripts
```

前端静态资源输出到 `dist/`。构建不会访问外部接口，也不会创建测试文件。

## 本地运行

先启动后端：

```bash
python3 scripts/run_server.py --host 127.0.0.1 --port 8765
```

再启动前端开发服务：

```bash
npm run dev
```

打开 `http://127.0.0.1:4317`。Vite 会把 `/api` 请求代理到同一个本机后端。

后端数据默认写入 `backend/var/state.json`。可以通过 `--data-dir` 指定其他目录。

## 环境变量

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `ORCHARD_ATLAS_HOST` | 服务监听地址 | `127.0.0.1` |
| `ORCHARD_ATLAS_PORT` | 服务监听端口 | `8765` |
| `ORCHARD_ATLAS_DATA_DIR` | JSON 快照目录 | `backend/var` |

浏览器工作流检查使用固定的本机端口 `8765` 和 `4317`，并使用临时数据目录。

## 工作流检查

三条检查都启动真实后端与真实 Vue 页面，通过浏览器完成关键步骤，再从 API 核对结果：

```bash
node scripts/workflow_check.mjs --workflow catalog
node scripts/workflow_check.mjs --workflow observe
node scripts/workflow_check.mjs --workflow compare
```

- `catalog`：建立园区、加入植株、确认园区并核对服务端状态。
- `observe`：建立季节志、补录四个必需阶段、完成并核对冻结结果。
- `compare`：准备两份同年已完成季节志，在页面生成比较并核对四条阶段偏移。

检查结束后会关闭服务、浏览器和临时数据目录。

## HTTP 接口概览

所有接口均以 `/api` 开头：

- `GET /api/health`：服务状态。
- `GET /api/stages`：固定物候阶段字典。
- `GET|PUT /api/plots`：查询或建立园区。
- `GET|PATCH /api/plots/{plot_id}`：读取或修订草稿园区。
- `PUT /api/plots/{plot_id}/confirm`：确认并冻结园区基础信息。
- `GET|PUT /api/trees`：查询或加入植株。
- `PUT /api/trees/{tree_id}/close`：标记植株退休或遗失。
- `GET|PUT /api/observations`：查询或建立季节志。
- `PATCH /api/observations/{id}`：修订草稿季节志说明。
- `PUT /api/observations/{id}/stages`：补录物候阶段。
- `DELETE /api/observations/{id}/stages/{stage}`：移除草稿中的阶段。
- `PUT /api/observations/{id}/complete`：完成并冻结季节志。
- `GET|PUT /api/comparisons`：查询或生成对比图谱。
- `GET /api/briefs` 与 `GET /api/briefs/{brief_id}`：查询编研简报。
- `PUT /api/plots/{plot_id}/briefs`：生成冻结简报。

## 数据与一致性

- 园区确认后不能直接修改基础信息；本基线不提供重新打开动作。
- 同一园区内植株编号唯一；定植年份不能早于园区起始种植年份。
- 同一植株、同一年份只能建立一份季节志。
- 完成后季节志不可增删阶段；完成前必须包含萌芽期、盛花期、坐果期和采收期。
- 比较只使用双方共同阶段，年份不同、状态未完成或无共同阶段时拒绝生成。
- 写入接口在进程锁内复制完整快照，使用临时文件、`fsync` 和原子替换提交；落盘失败不会替换内存状态。
- 修改类接口使用 `revision` 执行乐观并发控制，旧修订号返回冲突错误。

## 测试状态

本项目是初始化基线，`testing` 标记为 `deferred`。当前不包含单元测试、测试夹具或正式 E2E 测试套件，后续代码测试任务负责增加领域边界、仓储故障、并发修订和跨浏览器回归测试。

当前保留的 `workflow_check.mjs` 是生产级有界冒烟检查，用于证明三条业务路径可运行，不等同于完整测试套件。

## 当前范围

不提供多人账户、远程协作、外部气象数据、地图底图、数据删除、多节点部署和移动端原生应用。内置指南说明不替代农业技术结论。
