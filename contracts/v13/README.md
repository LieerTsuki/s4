# S4 v1.3 本地版本契约

本目录为 2026-10-30 需求迁移的显式新契约，与旧 `openkb.s3-s4.v1`、
`openkb.s4-review.v2`、`openkb.s4-s5.v1` 并存。新文件不更改旧封存的语义。

| Schema | 版本/用途 |
|---|---|
| source-envelope.schema.json | `openkb.s3-s4.v2`，新版候选、原始 S3 报告与最终 PASS 集合 |
| unit.schema.json | 13 类候选单元，英文难度、QA 新证据与拒答字段、专项结构 |
| review.schema.json | `openkb.s4-review.v3`，主核实与观测复核、逐对象理由/定位 |

Schema 由 `backend/src/openkb_s4/domain/v13.py` 的 Pydantic 模型生成。
集合关系、原始通过率/分母、摘要、Unicode 定位、D4 成对、D7 血缘、
SEC 基线时序等跨字段约束由同模块运行时校验，不应仅用 JSON Schema 宣称验收完成。

`examples/demo-import.json`、`examples/review-needs-revision.json` 均为合成数据。
复核例子的第二要点无支持，使用显式搜索范围并记录 `NEEDS_REVISION`；
不能在保留错误发现的同时给原始候选签 `VERIFIED`。

QA-D6 完整词表及 SEC-D2 攻击子类型原表未提供，不能从旧规范或示例推导。
运行时可接受结构化待修订记录；未取得独立批准的字典，不允许相应专项签核实通过。
字典的可信审批与正式 S3/S5 联调不由客户端载荷中的 `approved=true` 替代。

S4 过程输出使用 N 条核实记录及 n 条真实观测记录，不能把样本数当全量覆盖。
S4 过程包也不替代 S5 最终六文件；正式协议、J1/C1 出口规则及主仓索引映射仍须对接确认。
