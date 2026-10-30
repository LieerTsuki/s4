# S4 Architecture

当前需求为v1.3，入口`liyue/document/00_v1.3执行入口与文档索引.md`。新HTTP面`/api/s4/v2`复用既有会话，主线N条VERIFICATION与抽样n条OBSERVATION各有分配、封存和进度。原始κ仅观测，内容问题独立闭环，退S2的旧来源不能重标为通过。

新增0004—0006保存索引与引用：`models_v13`及`models_handoff_v13`；所有新版正文、gold、草稿、提交、修订、向量与原文件归档由`ContentStore`受控内容寻址保存。原始JSONL按字节保留，与规范化来源摘要分别登记。文件先封存，事务后发布引用，孤立对象保留并对账。

新版交接由独立worker执行EXPORT_V13，锁定来源范围并使用当前有效核实签名。交接为N候选/N核实/n观测/IAA及报告、动作和manifest，不替代S5最终六文件。发送前重新核对当前内容、质量动作与快照；重试返回同一发送历史，正式接收仍未对齐。

备份同一PG快照下的DB引用及其文件图，包含嵌套复算证据和原文件审计引用；恢复到新隔离库。定期worker也检查新版引用、发布包与遗留孤立对象，不自动删除或修写原封存。主仓SQLite/builder/typer/GitLab真实映射及历史正文物理外置见ADR，不能声称已经完成。

## 0003历史结构

以下是此前REVIEW v2的历史结构，旧API业务默认只读，不作为当前全量核实流程。

独立React工作台→同源FastAPI→PostgreSQL事务；纯领域模块提供profile、输入校验、抽样与κ。持久jobs由独立worker领取，导出只在文件完整且摘要核对后发布。

认证采用Argon2id与可撤销Cookie会话，写请求验证CSRF和Origin。角色条件与对象条件共同执行；敏感材料白名单随BLIND/REVIEW变化，读取记录材料族暴露。封存表由数据库追加权限保护。

数据库jobs同时承担事务出站登记与持久队列，不另建重复outbox表。worker使用SKIP LOCKED、租约及最多3次自动尝试；统计与快照都绑定冻结输入。快照含完整N、抽检n、原始配对和人工血缘，manifest不自包含hash。

0003将原文材料与草案拆成unit/gold revision，BLIND查询不加载完整来源或gold；新批次绑定已批准profile快照、manual与SHA256。v2复核固定三栏且逐对象有理由/定位；旧v1封存只读。材料工单暂停作业、BLIND整席位补派和迟到历史不改变原封存，REVIEW后换人仍通过校准完整新轮。

最终候选完整校验后，实质修订/定位修正由独立verifier复验；原κ和原始向量不回写。六文件中的报告附受控复算证据包，包含有效/撤销分配、原始提交、冻结profile、复验及截至定稿时的审计，避免导出重试因后续读取日志改变内容。文件IO在线程中执行，独立心跳和租约续期不会被fsync阻塞。

worker定期做幂等站内提醒和业务/文件/租约对账；发现只登记不自动覆盖历史。备份以PostgreSQL导出快照绑定dump/计数/已发布manifest，恢复始终写新隔离库。S3导入与S5回执使用独立服务scope；浏览器不持服务token。

实现依据见docs/specs中的初版设计与2026-10-28补全规范，规则映射见docs/requirements-alignment.md，运行和恢复见docs/operations.md。所有代码与数据限定本工程；旧管线与语源不接入。外部S3/S5尚未对齐，本地契约测试不构成联调或生产验收。
