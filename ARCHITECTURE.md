# S4 Architecture

独立React工作台→同源FastAPI→PostgreSQL事务；纯领域模块提供profile、输入校验、抽样与κ。持久jobs由独立worker领取，导出只在文件完整且摘要核对后发布。

实现依据见docs/specs/2026-10-27-s4-system-design.md，接口协作约定见docs/superpowers/plans/2026-10-27-s4-implementation.md。所有代码与数据限定本工程；旧管线与语源不接入。外部S3/S5尚未对齐，本地契约测试不构成联调或生产验收。
