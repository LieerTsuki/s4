# Codebase Map

当前处于初始研发：backend/src/openkb_s4/domain由领域任务维护；backend其他源码及数据库迁移由API任务维护；frontend由前端任务维护；根目录、deploy、scripts、docs和E2E由集成任务维护。

调用路径：前端api客户端→/api/s4/v1→认证及对象权限→领域规则/服务→SQLAlchemy事务。事务登记jobs→worker→统计/导出→回写状态与审计。最终文件和API清单随验证结果更新。
