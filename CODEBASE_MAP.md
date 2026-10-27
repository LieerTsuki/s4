# Codebase Map

| 目录/文件 | 职责 |
|---|---|
| backend/src/openkb_s4/domain | 严格输入/来源校验、12集profile、抽样、精确κ |
| backend/src/openkb_s4/models.py、db.py | PostgreSQL模型、唯一约束及请求事务 |
| backend/alembic | 冻结迁移0001与暴露范围迁移0002；运行角色权限 |
| backend/src/openkb_s4/security.py、api/auth.py | 密码、会话、CSRF、角色/对象条件、账号 |
| backend/src/openkb_s4/api/workflow.py | 导入、分发、阶段DTO、草稿/封存、统一开放、新轮 |
| backend/src/openkb_s4/api/quality.py | 原始统计、第三人/独立负责人、内容定稿 |
| backend/src/openkb_s4/api/exports.py | 快照、校验下载、受限回执、审计 |
| backend/src/openkb_s4/services | 白名单/暴露、事务jobs、不可变文件发布与复核 |
| backend/src/openkb_s4/worker.py、cli.py | 心跳/领取/恢复、first-admin互斥初始化 |
| backend/tests | 领域、真实PG API、并发/越权/恢复/篡改测试 |
| frontend/src/App.tsx、api.ts、pages、components | 会话与角色导航、中文作业/运营工作台、静态材料 |
| frontend/src/tests | 表单、会话缓存、协议、草稿冲突、材料投影回归 |
| contracts | 6份JSON Schema、profiles、demo/formal合成及失败样例 |
| deploy | digest固定镜像、同源Nginx、Compose、DB角色初始化 |
| scripts | 本机启动、专用E2E、契约/许可、备份与隔离恢复 |
| tests/e2e | 真实PG/worker API闭环与Edge表单封存 |
| docs | 已确认设计、实施计划、规则对齐、运行与验收记录 |

调用路径：前端api客户端→`/api/s4/v1`→认证及对象权限→领域规则/服务→SQLAlchemy事务。事务登记jobs→worker→统计/导出→回写状态与审计。OpenAPI由实际应用生成，运行时见`/api/s4/v1/docs`。
