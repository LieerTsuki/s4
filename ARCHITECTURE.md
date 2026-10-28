# S4 Architecture

独立React工作台→同源FastAPI→PostgreSQL事务；纯领域模块提供profile、输入校验、抽样与κ。持久jobs由独立worker领取，导出只在文件完整且摘要核对后发布。

认证采用Argon2id与可撤销Cookie会话，写请求验证CSRF和Origin。角色条件与对象条件共同执行；敏感材料白名单随BLIND/REVIEW变化，读取记录材料族暴露。封存表由数据库追加权限保护。

数据库jobs同时承担事务出站登记与持久队列，不另建重复outbox表。worker使用SKIP LOCKED、租约及最多3次自动尝试；统计与快照都绑定冻结输入。快照含完整N、抽检n、原始配对和人工血缘，manifest不自包含hash。

0003将原文材料与草案拆成unit/gold revision，BLIND查询不加载完整来源或gold；新批次绑定已批准profile快照、manual与SHA256。v2复核固定三栏且逐对象有理由/定位；旧v1封存只读。材料工单暂停作业、BLIND整席位补派和迟到历史不改变原封存，REVIEW后换人仍通过校准完整新轮。

最终候选完整校验后，实质修订/定位修正由独立verifier复验；原κ和原始向量不回写。六文件中的报告附受控复算证据包，包含有效/撤销分配、原始提交、冻结profile、复验及截至定稿时的审计，避免导出重试因后续读取日志改变内容。文件IO在线程中执行，独立心跳和租约续期不会被fsync阻塞。

worker定期做幂等站内提醒和业务/文件/租约对账；发现只登记不自动覆盖历史。备份以PostgreSQL导出快照绑定dump/计数/已发布manifest，恢复始终写新隔离库。S3导入与S5回执使用独立服务scope；浏览器不持服务token。

实现依据见docs/specs中的初版设计与2026-10-28补全规范，规则映射见docs/requirements-alignment.md，运行和恢复见docs/operations.md。所有代码与数据限定本工程；旧管线与语源不接入。外部S3/S5尚未对齐，本地契约测试不构成联调或生产验收。
