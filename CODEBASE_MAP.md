# Codebase Map

| 目录/文件 | 职责 |
|---|---|
| backend/src/openkb_s4/domain | 严格输入/来源校验、12集profile、抽样、精确κ |
| backend/src/openkb_s4/models.py、db.py | PostgreSQL模型、唯一约束及请求事务 |
| backend/alembic | 0001/0002与0003增量迁移；配置/材料revision、替换历史及受限角色权限 |
| backend/src/openkb_s4/security.py、api/auth.py | 密码、会话、CSRF、角色/对象条件、账号 |
| backend/src/openkb_s4/api/workflow.py | 导入、分发、阶段DTO、草稿/封存、统一开放、新轮 |
| backend/src/openkb_s4/api/quality.py | 原始统计、第三人/独立负责人、内容定稿 |
| backend/src/openkb_s4/api/governance.py | 配置审批、材料工单、整席补派、校准资格、独立复验候选及证据 |
| backend/src/openkb_s4/api/operations.py、services/operations.py | 对账、队列/备份指标与本人站内通知 |
| backend/src/openkb_s4/api/exports.py | 快照、校验下载、受限回执、审计 |
| backend/src/openkb_s4/services | 白名单/暴露、事务jobs、不可变文件发布与复核 |
| backend/src/openkb_s4/worker.py、cli.py | 独立心跳/续租/attempt fencing、定期对账、first-admin及本机备份管理 |
| backend/tests | 领域、真实PG API、并发/越权/恢复/篡改测试 |
| frontend/src/App.tsx、api.ts、pages、components | 会话与角色导航、中文作业/运营工作台、静态材料 |
| frontend/src/tests | 表单、会话缓存、协议、草稿冲突、材料投影回归 |
| contracts | 8份JSON Schema、OpenAPI/profile、v2与demo/formal合成及失败样例 |
| deploy | digest固定镜像、同源Nginx、Compose、DB角色初始化 |
| scripts | 本机启动、生成契约/类型、整体及增量覆盖门、迁移摘要核对、许可、快照备份及隔离恢复 |
| tests/e2e | 真实PG/worker API闭环、Edge三栏/封存/发送与2200单元11并发容量检查 |
| docs | 已确认设计、实施计划、规则对齐、运行与验收记录 |

调用路径：前端api客户端→`/api/s4/v1`→认证及对象权限→领域规则/服务→SQLAlchemy事务。事务登记jobs→worker→统计/导出→回写状态与审计。OpenAPI由实际应用生成，运行时见`/api/s4/v1/docs`。
