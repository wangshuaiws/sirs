# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指引。

## 项目概述

SIRS（股票信息及研究系统）— A 股股票分析 Web 应用。V1 功能：股票数据初始化导入、每日收盘后同步、K线图（含 MA 均线指标）、股票分组管理、用户注册登录（含验证码）。

三层架构：**Python 数据管道**（akshare → PG + TDengine）、**Java Spring Boot 后端**（REST API）、**Vue 3 前端**（深色主题 SPA）。PostgreSQL 存储元数据（用户、股票、分组），TDengine 存储 K 线时序数据。

## 常用命令

```bash
# 基础设施（需要 Docker Desktop）
docker compose up -d                 # 启动 PG:5432、TDengine:6030/6041、Redis:6379
docker compose ps                    # 确认三个容器均已 Up（healthy）
docker compose down                  # 停止所有服务

# Python 数据管道（需要 Python 3.12，通过 pyenv 管理）
cd data-pipeline
source venv/bin/activate
python init_stocks.py                # 导入全部 A 股列表 + 历史日K线
python daily_sync.py                 # 增量同步最近交易日数据
python daily_sync.py --date 2025-01-15  # 同步指定日期

# Java 后端（需要 JDK 21 + Maven，在 IntelliJ IDEA 中开发）
cd backend
mvn spring-boot:run                  # 启动后端，端口 :8080
# 或者：在 IDEA 中以 Maven 项目打开 backend/，运行 SirsApplication.main()

# 前端（需要 Node 18+）
cd frontend
npm install                          # 首次运行前安装依赖
npm run dev                          # Vite 开发服务器，端口 :5173，代理 /api → :8080
npm run build                        # 生产构建
npx vue-tsc --noEmit                 # 仅类型检查，不生成文件
```

## 架构

### 数据流

```
akshare（免费 A 股数据源）
  → Python init_stocks.py / daily_sync.py
  → PostgreSQL（stocks 表） + TDengine（kline_1d 超级表，每只股票一个子表）
  → Java REST API（/api/*）
  → Vue 3 SPA（深色主题，ECharts K线图）
```

### PostgreSQL 表

- `stocks` — A 股主列表（code、name、exchange SH/SZ）
- `users` — 用户凭证，BCrypt 哈希存储
- `groups` — 用户自建的股票分组，关联 users(id)
- `group_stocks` — 分组与股票多对多关联，级联删除

### TDengine 模型

超级表 `sirs.kline_1d`，列：`ts, open, high, low, close, volume, amount, turnover`。每只股票一个子表 `k_1d_{code}`，标签 `(code, name)`。周K/月K 通过 SQL 中的 `INTERVAL(1w)` / `INTERVAL(1mo)` 实时聚合计算 — **不单独存储**。分钟级 K 线为 V2 范围。

### Java 后端分层

- **拦截器鉴权**：`AuthInterceptor` 从 `Authorization: Bearer` 头读取 JWT，将 `userId`/`username` 写入 request attributes；**限流**：`RateLimitInterceptor` 使用 Bucket4j 内存限流，仅对 `/api/auth/register` 生效
- **全局异常处理**：`GlobalExceptionHandler` 捕获 `BusinessException` 和参数校验异常，统一返回 `Result` 格式
- **认证**：密码使用双重 MD5+盐（简化方案；生产环境应迁移至 BCrypt），JWT 7 天过期，验证码通过 easy-captcha 生成并存入 Redis（5 分钟 TTL）
- **TDengine 查询**：Java 后端通过 `java.net.http.HttpClient` 调用 TDengine REST API（端口 6041），而非 JDBC。KlineServiceImpl 使用 `INTERVAL` 聚合构建周K/月K 的 SQL 查询
- **Service 层权限校验**：所有 `/api/groups/**` 接口在 `GroupServiceImpl.getAndVerifyOwner()` 中校验 `group.userId == currentUserId`

### API 响应格式

```json
{"code": 0, "msg": "success", "data": {}, "timestamp": 1752864000}
```

错误码：`0`=成功，`1xxx`=系统错误，`2xxx`=用户错误，`3xxx`=股票错误，`4xxx`=分组错误。定义在 `ErrorCode.java`。

### 前端规范（遵循 Vue Skills）

- **Composition API** + 所有组件使用 `<script setup lang="ts">`
- **`shallowRef`** 用于所有原始值（Vue 3.5+ 最佳实践），**`useTemplateRef`** 用于模板引用
- **SFC 顺序**：`<script>` → `<template>` → `<style scoped>`
- **类选择器** 用于 scoped CSS，采用 BEM 风格命名（`.block__element--modifier`）
- **Composables** 从视图提取：`useStockSearch`、`useKlineData`、`useChart`、`useGroupManager`
- **深色主题**：CSS 变量定义在 `global.css`，Element Plus 深色 CSS 变量在 `main.ts` 中导入
- **Pinia**：状态通过 `storeToRefs` 访问，actions 直接解构；auth store 使用 setup 函数语法
- **路由结构**：`/login`、`/register`（无导航栏），`/`（K线主页），`/groups`（分组管理）
- **技能文件**：`.claude/skills/vue-best-practices/SKILL.md` 及其 `references/` 目录包含详细的 Vue 编码规范

### 关键配置值

| 配置项 | 值 |
|--------|-----|
| PG 地址/端口/库/用户/密码 | localhost:5432/sirs/sirs/sirs123 |
| TDengine REST | localhost:6041（用户: root，密码: taosdata） |
| Redis | localhost:6379 |
| Java 端口 | 8080 |
| Vite 端口 | 5173 |
| JWT 密钥 | `sirs-jwt-secret-key-change-in-production-20250713` |
| JWT 过期时间 | 7 天 |
| 限流 | 每 IP 1 次/秒，5 次/分钟（仅注册接口） |

### Vite 代理

Vite 开发服务器将所有 `/api` 请求代理到 `http://localhost:8080`，因此测试前端前必须先启动 Java 后端。
