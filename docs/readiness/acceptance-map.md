# V3-Q01—Q22与08附加验收映射

截至2026-11-05，这是**可执行映射与证据范围审查**。测试函数存在不等于本日已跑，通过子场景不等于完整业务用例通过。本文对完整V3用例均保留待验/部分证据，实际执行记录填写 [验收空表](templates/acceptance-runs.csv)。

来源：[07 V3验收定义](../../../document/07_双盲分发队列方案设计.md)、[08 §14](../../../document/08_OpenKB-Eval_S4双盲标注与质量控制系统_自研实现方案.md)。历史证据：[E31 10/31本地](../audits/2026-10-31-v13升级验收.md)记317后端/102前端和N12/n8合成；[E02 11/02](../audits/2026-11-02-前期任务核查与补欠清单.md)仅44项针对性回归；[E03 11/03麦芽](../audits/2026-11-03-麦芽部署适配核查.md)为QA-D1两个不同来源的N2与n8合成。0003/REVIEW v2和旧Q01—Q22只作历史，不继承新版结果。

本地测试文件简称均有链接：D=[test_v13_domain.py](../../backend/tests/test_v13_domain.py)，W=[test_v13_workflow.py](../../backend/tests/test_v13_workflow.py)，R=[test_v13_review.py](../../backend/tests/test_v13_review.py)，H=[test_handoff_v13.py](../../backend/tests/test_handoff_v13.py)，HA=[test_v13_handoff_api.py](../../backend/tests/test_v13_handoff_api.py)。用下表完整函数名选择执行；例如在仓库根运行 `.venv/Scripts/python.exe -m pytest backend/tests/test_v13_domain.py::test_quality_actions_use_exact_boundaries_and_undefined_not_one -q -o addopts=''`。W/R/HA及其他API测试须使用项目真实测试DB配置与隔离fixture，不能指向生产库。项目标准入口另见README；此表不要求为材料准备启动线上操作。

| 用例 | 现存函数/覆盖子范围 | 历史/麦芽证据范围 | 本轮仍需执行并归档的具体检查 |
|---|---|---|---|
| V3-Q01 | W `test_v13_all_units_have_main_tasks_and_partial_completion_never_ready`实际12条只完成1条，显示缺11 | E31双轨；E03分别主线2/2、另一源0/8；均非12中8 | 冻结N12，完成8条且有效κ正常（κ=1须非退化混合标签），核实缺4、不READY；保存报告与12条集合 |
| V3-Q02 | H `test_package_never_uses_observation_to_fill_verification_gaps`有missing_pair；HA全量/观测合成流程 | E03 N2无观测与另一源n8无主线，明确分账 | 同一来源N全核实后，仅A或缺样本，分别记录核实完成、配对/最低数缺口及拒交接 |
| V3-Q03 | W `test_v13_observation_barrier_and_foreign_task_are_server_enforced`只含B取A详情404；R `test_participant_lead_cannot_list_other_track_of_same_source`；HA外人文件拒绝 | E03 A/B互取主任务404、若干角色401/403 | A→B、B→A逐一查列表/详情/附件/导出/统计，伪造actor_id，记录HTTP及无敏感响应；现存覆盖不包全部路径 |
| V3-Q04 | W `test_v13_observation_barrier_and_foreign_task_are_server_enforced`明确A8+B7→409 | E03 observation-workflow相同15/16屏障 | 目标版本复跑，保存16份清单、15份状态和提前释放响应；核主线账不变 |
| V3-Q05 | W同函数补第16份→释放200；HA两人REVIEW全流程 | E03补16/16→200、BLIND投影无gold/points | 目标环境双方REVIEW同草案hash/不同人员、互不可见；不只验证释放响应 |
| V3-Q06 | D `test_gold_rejects_non_gold_grades`、`test_strict_partitions_and_storage_enums`、`test_review_covers_gold_and_ranking_documents_and_moves_explicitly` | E31本地字段；E03仅合法表单 | gold1/0、ranking2/3、重复doc逐项实际提交，拒绝且不落最终gold；修订建议另存 |
| V3-Q07 | D `test_strict_partitions_and_storage_enums` | E31本地；E03只合法boolean | 各传字符串/数字boolean、D4C=true、中文difficulty，保存逐项422/错误码；不以界面禁选代服务端 |
| V3-Q08 | H `test_package_never_uses_observation_to_fill_verification_gaps[same_observer]`仅同annotator包校验，未证明两个账号同person_id分配 | E03五测试身份不能证明实际人隔离 | 同一真实person_id两账号占A/B分配应拒绝；另核不同person_id，保留真实身份映射受控引用 |
| V3-Q09 | W `test_v13_draft_revision_and_submission_idempotence`；R `test_replacement_is_whole_observation_seat_and_late_history_is_invalid` | E31本地；E03有草稿恢复/封存，未测并发/迟到 | 原键同payload同结果、异payload409；旧人迟到无效历史、草稿stale409；补并发版本操作证据 |
| V3-Q10 | R `test_replacement_is_whole_observation_seat_and_late_history_is_invalid`、`test_review_departure_starts_independent_new_round_preserving_scope`、`test_new_primary_round_appends_same_revision_without_counting_old_seal` | E31本地；E03未测 | 主线逐任务补派与观测全席补派分别操作；REVIEW新轮全范围，原人员对/轮次不混算 |
| V3-Q11 | R `test_unregistered_profile_and_changed_frozen_schema_are_rejected`、`test_new_primary_round_binds_current_final_candidate_without_inheriting_old_signature` | E31本地；旧v1生命周期不证明v2正式配置 | 分别改内容/manual/profile，检查新revision/轮次、旧提交hash不变；新版生命周期单列A04 |
| V3-Q12 | W `test_v13_uploaded_drafts_disqualify_observer_and_small_sample_records_shortfall`；R `test_observer_cannot_open_primary_gold_before_own_observation_blind`、`test_transitive_family_scope_covers_intermediate_unassigned_units` | E03主核实暴露后首次观测409 | 同源和传递D1/D7、D4/D4C暴露；含读导入/会议/附件记录。核UNKNOWN暴露不放行 |
| V3-Q13 | D `test_quality_actions_use_exact_boundaries_and_undefined_not_one`测0.8/0.6/低值，未直接构造0.7 | E31本地阈值；E03仅pe=1 | 使用human-drills冻结向量核0.7/0.699/0.6/0.599；阈值前不舍入；保留原输出 |
| V3-Q14 | D同函数测UNDEFINED；HA允许demo包且formal_credential=false | E31 null/WAITING_POLICY；E03 null，NOT_ALIGNED | 灰区与null分别申请正式交接，真实适用规则缺失时待确认；主线可继续；不得把demo导出当正式通行 |
| V3-Q15 | R `test_low_kappa_returns_entire_source_and_ack_cannot_reopen`；H `test_returned_scope_cannot_be_relabelled_ready` | E31本地；E03未测 | 低值退全source；仅关闭问题/ack不能READY；取得真实S2接收、新生成、新S3/S4血缘 |
| V3-Q16 | D `test_d4_pairing_reports_missing_side_na_and_strata_mismatch`测缺侧/难度错，未直接证明>20%比例 | E31本地；E03无D4 | 缺侧、同域同难度不符、规模差>20%三个反例，双指标N/A/成对缺口；T0决定单独引用 |
| V3-Q17 | D `test_d6_span_digest_and_relation_references_without_invented_vocabulary`、`test_d6_trusted_vocabulary_hook_rejects_unknown_types` | E31合成字典；E03未测 | 取得真词表后逐验词表外/悬空/emoji/摘要；合成ORG/LOC不当正式字典批准 |
| V3-Q18 | D `test_sec_effect_and_poison_baseline_materials`、`test_rank_uses_position_and_absence_is_n_plus_one` | E31合成专项；E03未测 | 真D2判据缺失、D3后采/过期基线、D4只看排名；组/对各算1，实际检测/rollback材料不代造 |
| V3-Q19 | W `test_v13_uploaded_drafts_disqualify_observer_and_small_sample_records_shortfall`测n2缺6，未完成两条主线 | E03主线2与另一源观测8不能组合 | 同源N2做主线2；观测最多2/最低8缺6，报告短缺，不复制凑8 |
| V3-Q20 | H `test_package_never_uses_observation_to_fill_verification_gaps`多种缺漏/revision；`test_receiver_recomputes_declared_unit_set_digest` | E31本地包；E03未发送S5 | 真S5入口对缺主线、只n、错revision/摘要分别拒收，保留接收方原始回执 |
| V3-Q21 | HA `test_full_verification_and_observation_publish_v2_with_real_worker`测job、幂等sent/无假receipt；[test_recovery.py](../../backend/tests/test_recovery.py) `test_export_io_failure_is_bounded_then_explicit_retry_publishes_once`属旧链路 | E31独立worker本地；E03未导出/中断/发包 | 新版worker在受控环境中断、残包不发布、租约恢复、已发送丢回执先对账；旧链路测试不覆盖新版全故障矩阵 |
| V3-Q22 | D阈值函数及H包复算只是程序证据 | E31/E02合成；E03无真人独立复算/七层接收 | 另一真实人员读同一冻结成对向量，留po/pe/κ、工具与签认；S5七层逐层独立结论 |

## 08附加验收

| ID / 要求 | 可复用实际文件/函数及旧证据 | 具体执行与待验边界 |
|---|---|---|
| A01 正文/gold不入DB与日志 | W `test_v13_source_and_submissions_are_only_content_references_in_database`；[test_v13_root_review.py](../../backend/tests/test_v13_root_review.py) `test_database_nonnull_reference_shape_is_never_silently_ignored`；[test_api.py](../../backend/tests/test_api.py) `test_unexpected_failure_returns_safe_json_without_secret_logs` | 审计所有新版嵌套source/draft/submission/revision/vector及日志；旧PG历史正文仍只读存在，物理外置待受控迁移决定 |
| A02 主仓SQLite单annotator | [存储ADR](../adr/2026-10-30-v13-storage-and-main-repo-boundary.md)只述边界 | 真DDL逐字段映射、真实同步回读与IAA不入单人表；当前无主仓集成完成证据 |
| A03 builder/typer/GitLab/依赖 | 本地scripts/v13_ci.py与GitLab配置仅本地准备 | 取主仓入口、CI五门原件/运行URL及甲方评审；CLI等待/恢复不重跑S3；分支/依赖ADR按实际核对 |
| A04 新版配置生命周期 | R `test_unregistered_profile_and_changed_frozen_schema_are_rejected`只有冻结冲突；旧[test_governance.py](../../backend/tests/test_governance.py)审批测试不继承 | 新版draft→review→独立approval→retired、反自批/stale/退休后拒新绑定/旧快照保留；真实批准仍必须取得 |
| A05 D6码点/词表 | D的D6两函数；[v13.test.tsx](../../frontend/src/tests/v13.test.tsx)“D6用Unicode码点坐标，删除实体同时移除悬空关系” | 真词表/hash与UTF-16↔码点往返；13类+OTHER、关系原表+OTHER_REL，不臆造 |
| A06 三类契约能力协商 | D `test_published_v13_schemas_and_synthetic_examples_match_runtime`；[test_v13_compatibility.py](../../backend/tests/test_v13_compatibility.py) `test_legacy_business_writes_are_readonly_by_default` | S3-S4.v2/review.v3/S4-S5.v2真实双方协商；错误版本/缺能力拒绝；HTTP前缀与数据semver分别记 |
| A07 S3原始分母与分数语义 | D `test_s3_preserves_denominator_and_requires_current_passes` | 真≥90%报告、最终逐条PASS、模型/校准版本、NLI禁LLM；原分不冒概率；S4不替S3模型验收 |
| A08 S5七层/最终六文件 | H本地包摘要/集合；E31不含外部接收 | 使用external-handoff逐层材料；真实拒收/回执、金丝雀/密封抽检独立；S4过程包非最终六文件 |
| A09 恢复/私有存储/权限 | [test_v13_backup.py](../../backend/tests/test_v13_backup.py)两个函数、[test_v13_reconcile_checks.py](../../backend/tests/test_v13_reconcile_checks.py)；E31独立恢复 | 麦芽DB+文件一致性恢复、共享私有目录、备份实际运行、Cookie Secure、角色撤销/缓存/CSRF；E03未重启恢复 |
| A10 容量/安全运行 | E31仅2300 QA-D1合成/11会话；E03仅10小单元 | 目标环境按实际13类/正文大小、11会话、上传超时/worker积压测；批准目标与实际p50/p95/错误率/RPO/RTO分开 |

每项实际记录至少含：代码提交/构建资产、迁移、环境、协议/manual/profile/hash、输入受控hash、真实操作者/角色、操作/命令、预期与实际、脱敏原始证据位置、子范围、未验项、复核者。遇到失败登记缺陷，不把材料缺失叫代码失败；遇到未执行保留NOT_EXECUTED。表中的历史证据不改写成2026-11-05新测试结果。

## 11月5日本地新增证据补充

A04/V3-Q11新增独立v2生命周期实现和测试：[领域与冻结漂移回归](../../backend/tests/test_profile_lifecycle_v13.py)、[真实PG API/退休/指南/篡改](../../backend/tests/test_profile_api_v13.py)、[配置证据导出与恢复引用图](../../backend/tests/test_profile_export_v13.py)、[前端操作与建队选择](../../frontend/src/tests/v13ProfileLifecycle.test.tsx)、[实际浏览器配置闭环](../../tests/e2e/profile_lifecycle.spec.js)。独立审批、正文外置、冻结指南、退休禁新绑定和运行时核心漂移拒绝均有本地证据；正式批准、目标环境部署和真人活动仍待完成。

旧基线和当前快照仍独立保存。新增材料不把上表的外部待验改成通过；本次执行细目与最后验证结果见`docs/audits/2026-11-05-前期补欠交付与验证.md`。

## 11月8日本地收口

A04新增审批员在REVIEW行只读核对对应revision/hash、指南及完整配置的真实组件回归，原审批P2已修复；A09恢复工具增加审计失败不发布成功proof的正反回归。完整重跑、隔离恢复/迁移及交付状态见[本轮收尾报告](../audits/2026-11-08-可独立补欠交付与验证.md)。这些是本地技术证据，表中真实人/麦芽/外部待验场景仍按原范围保留，未替其签通过。
