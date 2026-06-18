# scripts/migrations/

数据库 schema 与核心数据的**变更日志**目录。

## 这不是自动化迁移系统

实际生产中由 DBA 按工单流程执行。本目录仅用于：
- 让后续开发者能看到历次变更内容
- 让 DBA 拿到可直接审阅的 SQL 脚本

应用代码**不读取本目录、不校验版本、不参与启动**。

## 命名规则

```
NNNN_<snake_case_description>.sql
```

- `NNNN` —— 4 位零填充编号，单调递增
- `<description>` —— 用 snake_case 简短描述（如 `add_tenant_selection_column`）

## 文件 header 模板

每个 .sql 文件以注释起头：

```sql
-- <one-line summary>
--
-- Background:
--   <为什么需要这次变更，关联 commit / spec>
--
-- Apply:
--   <这里是真正的可执行 SQL>
--
-- Rollback:
--   <回滚思路，或显式说明不可逆>
```

## 与 scripts/init_db.sql 的关系

- `scripts/init_db.sql` —— 当前完整 schema 快照，新环境从零部署使用
- `scripts/migrations/NNNN_*.sql` —— 单调递增的 diff 链

两者**应保持一致**：每次新增一个 migration，同时把对应 DDL 同步到 `init_db.sql`。

## 应用方式

### 本地开发

```bash
mysql -u root mini_router < scripts/migrations/0001_add_tenant_selection_column.sql
```

### 生产部署

由 DBA 按内部流程执行。**部署节奏**详见各 PR 的 release note；本仓库目前已有的部署约定：

1. PR 合并到 main 后
2. 先在 dev/staging 跑非破坏性 migration（如 ALTER ADD COLUMN）
3. 部署新代码 → 观察
4. 数据清洗类 migration（不可逆）在新代码稳定 ≥24h 后执行
