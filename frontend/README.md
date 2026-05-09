# MASE Memory Platform

MASE Memory Platform 是本仓库的本地可视化产品界面，用于管理、审计和运营 MASE 双白盒记忆系统。

## 功能

- 运营 cockpit：KPI、趋势图、分类分布、系统地图和快捷动作
- 健康检查、模型配置和记忆库指标总览
- OpenAI-compatible Chat Completions 调用
- Orchestration Trace 查看与 JSON 导出
- Facts-first recall、current-state 和 explain 联动检索
- Entity Fact Sheet 写入、筛选、历史查看和归档
- Event Log 写入、纠错 supersede、时间线查看
- Session state 写入、TTL 查询和删除
- Procedure 注册、筛选和快照管理
- Tenant / workspace / visibility 全局 scope 过滤
- Internal API key 本地配置，用于受保护的写入端点
- Read-only audit mode，只观察和调试，不允许持久写入

## 开发启动

```bash
cd E:\MASE-demo
pip install -e ".[server]"
python -m integrations.openai_compat.server
```

另开终端：

```bash
cd E:\MASE-demo\frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。开发服务器会把 `/health` 和 `/v1/*` 代理到 `http://127.0.0.1:8765`。

如需改用远端 API，在 `frontend\.env` 中设置：

```env
VITE_API_BASE=http://127.0.0.1:8765
# 可选：本地开发便利项。也可以直接在侧边栏输入，不建议提交真实 key。
VITE_MASE_INTERNAL_API_KEY=
```

如果后端设置了 `MASE_INTERNAL_API_KEY`，前端侧边栏需要填入同一个 key，写入、删除、纠错和快照生成请求会自动携带 `Authorization: Bearer <key>`。

## 构建

```bash
npm run build
```

构建产物写入 `frontend\dist`。当该目录存在时，后端会自动托管前端：

```bash
cd E:\MASE-demo
python -m integrations.openai_compat.server
```

打开 `http://127.0.0.1:8765` 即可使用单进程产品模式。

## 一键启动产品模式

```powershell
Set-Location -LiteralPath 'E:\MASE-demo'
.\scripts\start_platform.ps1
```

可选参数：

```powershell
.\scripts\start_platform.ps1 -Port 8779 -ReadOnly
```

`-ReadOnly` 会设置 `MASE_READ_ONLY=1`，后端会拒绝持久写入；前端会展示只读模式并禁用写入类按钮。
