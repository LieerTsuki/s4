# S4 Architecture

独立React工作台→同源FastAPI→PostgreSQL事务；纯领域模块提供profile、输入校验、抽样与κ。持久jobs由独立worker领取，导出只在文件完整且摘要核对后发布。

认证采用Argon2id与可撤销Cookie会话，写请求验证CSRF和Origin。角色条件与对象条件共同执行；敏感材料白名单随BLIND/REVIEW变化，读取记录材料族暴露。封存表由数据库追加权限保护。

数据库jobs同时承担事务出站登记与持久队列，不另建重复outbox表。worker使用SKIP LOCKED、租约及最多3次自动尝试；统计与快照都绑定冻结输入。快照含完整N、抽检n、原始配对和人工血缘，manifest不自包含hash。

实现依据见docs/specs/2026-10-27-s4-system-design.md，规则映射见docs/requirements-alignment.md，运行和恢复见docs/operations.md。所有代码与数据限定本工程；旧管线与语源不接入。外部S3/S5尚未对齐，本地契约测试不构成联调或生产验收。
