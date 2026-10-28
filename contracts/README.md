# S4 本地输入输出契约

这些契约用于独立S4研发，版本为 `openkb.s3-s4.v1`。尚未与其他人员联调；完整的本地Schema校验也不能证明来源真实或外部系统已接入。

## 导入

候选通过受控API以内联JSON提交，或使用`/imports/upload`的JSON包装`{filename,units_jsonl,envelope,source_index?}`上传UTF-8 JSONL与报告/原文索引。只读取本次上传内容，不接受任意主机文件路径、远程下载地址或目录穿越引用。原文件hash与归一化hash分开保存及备份。单次最多2200个单元；unit_id在输入中唯一，dataset为十二集之一，difficulty为简单/中等/困难。

所有普通QA必须附可阅读范围的原文contexts，而不能只给答案句的金标引用。每个原文有doc_id和text，金标gold_doc_ids必须能在允许原文范围中定位。多要点逐条保留；D4的空要点是有意设计，不能补假点。D6使用chunk/quality_metrics，SEC使用payload、expected_behavior、acl_context，SEC-D3另有inject_plan，不能带QA金标。

`demo`接收合成材料，用于本地功能和失败路径验证；从不产生正式生产凭据。`formal`要求完整S3证据：

- 原始checked_count、passed_count、failed_count及original_results（逐条PASS/FAIL），能够重算原始通过率且≥93%。
- 最终unit_results与当前选中unit_id集合一致，每条PASS；有原始要点的QA必须附逐点point_results，包含point_key、point/content SHA256、不同模型reverse及版本/coverage=1、逐点BART-MNLI版本/分值；[0.45,0.65]模糊带须附LLM兜底通过证据。单元聚合分数不能替代逐点覆盖。此字段映射为本地PROVISIONAL，结构正确不证明真实S3执行。
- 原始失败有archived_failures引用；最终未决失败数为0。replacement_lineage保留替换关系，不能删原始失败改分母。
- source_manifest绑定batch_id、source_revision、选中数量、代码/生成时间和内容摘要；checksums绑定units及contexts摘要。上下文带版本、文本SHA256、license及source_url。
- 缺少证据或摘要、数量、身份不一致时拒绝。对尚未冻结的专项规则和未对齐外部接口记录阻塞，不能仅声明passed=true就通过。

SHA256规范：UTF-8，JSON使用ensure_ascii=False、sort_keys=True、separators=(",", ":")、禁止NaN/Infinity。unit摘要计算原始unit完整对象；units摘要计算按输入顺序的units数组；contexts摘要计算按输入/原文顺序展平的contexts数组；原文text摘要直接计算UTF-8文本。校验后不会凭空加入默认字段改变来源摘要。

## 统计与profile

有答案点QA使用三类原始标签的Cohen's κ，阈值≥0.7 ACCEPT、[0.6,0.7) ARBITRATE、<0.6 REJECT_BATCH。分类向量缺配对、为空或pe=1时BLOCKED，kappa=null；不做单题κ，也不改用0.8、置信区间下界或三栏最小κ。

十二集总配额2200。D4/D6/SEC的专项统计单位未冻结，不能挪用通用要点κ；D7需已确认的evaluation_k放大规则记录，系统不自定倍率。当前版本没有已确认的D7规则，导入材料自带的“审批”不能清除其阻塞。profiles.json展示配置和阻塞原因，profile摘要按上述规范计算。

新复核协议为`openkb.s4-review.v2`，见`review-v2.schema.json`及`examples/review-v2.json`。逐点/逐文档/题级理由及Locator有明确类型；wrong无支持依据允许空定位加明确已核查授权范围。字典集合、文档/版本/坐标范围及专项字段按冻结单元进一步校验，JSON Schema本身不替代这些交叉约束。旧v1封存只读，不能补造新理由。

profile是有独立审批、手册版本和摘要的有限注册配置。input_schema/review_schema/review_fields只接受已实现策略的组合，完整类型由本目录Schema/OpenAPI公开；不声明能动态执行任意获批JSON Schema。PATCH配置草稿带expected_revision防止旧视图覆盖。

## 结果导出

S4快照包含 `units_for_s5.jsonl`（完整N）、`labeled.jsonl`（抽检n）、`iaa_records.jsonl`（同n）、`s4_report.json`、`arbitration_log.jsonl`及`s4_handoff_manifest.json`。未抽检单元不伪造人工标签；manifest不自包含自身SHA256。

这些过程文件不是S5六文件。S4_READY、HANDOFF_SENT、S5_ACCEPTED/S5_REJECTED是独立状态；真实接收方仍需复校，默认外部未对齐。本地测试接收桩不得伪装真实S5。

新报告增加`evidence_bundle`及规范SHA256，结构见`evidence-bundle.schema.json`：原始来源、有效/历史分配、各阶段封存、原向量和profile、完整定稿、独立复验、校准、仲裁确认和截至定稿的审计。legacy未保存的profile字段明确为null且标记legacy；不补造历史。原六文件不重写，旧报告仍可按旧字段读取。

发送事件绑定实际交付证据；正式回执另绑定sent_event_id、destination_ref与独立idempotency_key。S3导入服务凭据与S5回执凭据及scope分离。demo和未对齐契约持续拒绝正式接收，不用这些字段自证正式接入。

结构契约分别为 `handoff-manifest.schema.json`、`s4-report.schema.json`、`export-unit.schema.json`、`iaa-record.schema.json` 和 `arbitration-record.schema.json`。JSONL文件按行应用对应Schema；labeled行另需annotation_batch_id和round，且full/labeled/iaa集合及计数必须由运行时复核。Schema描述本地格式，不替代文件摘要重算、权限/双盲检查、人工闭环或真实外部验收。

## 合成样例

`examples/demo-import.json`全部为虚构测试材料，包含12个单元，可核对全量12与抽检8的区别。草案有意保留部分错误，供演练逐点判断；它不是生产S3或真人双盲证据。

`examples/synthetic-formal-contract-test.json`只有合成模型、合成原文与合成报告，演示原始95/100和最终8条PASS的契约形状。它通过本地证据一致性校验后仍标记 `EXTERNAL_CONTRACT_NOT_ALIGNED`，不证明真实S3执行、生产验收或外部接入。`invalid-formal-assertion.json`演示仅声明passed=true被拒绝；`invalid-washed-denominator.json`演示将原始分母从100清洗为95被拒绝。
