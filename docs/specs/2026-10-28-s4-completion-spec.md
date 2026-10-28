# S4补全规范：字段、状态、接口与验收

版本：V1.1补充稿，2026-10-28。用户已要求方案与代码同步补齐；本文件作为08第19节的工程细则。实现状态以新增验收记录为准，不因本文件存在认定开发完成。

## 1. 不改变的规则与版本兼容

继续执行2/1/0、四种answerable、要点三分类、10%/至少8条、κ≥0.7接受/[0.6,0.7)仲裁/<0.6全批重标，以及整批BLIND封存后才开放REVIEW。S3原始通过率≥93%，N全量/n抽检分离。S3/S5仍未对齐；D4/D6/SEC统计及D7倍率不由研发发明。

新增协议为`openkb.s4-review.v2`，API前缀仍`/api/s4/v1`。原有封存、来源、统计和导出不回写、不补造理由；旧v1保持可读并标明legacy。新建批次绑定完整profile快照、版本与SHA256；未完成的旧批次通过有原因的新轮升级，不把旧标签改名当v2。新建v2作业强校验新增结构；存量v1行为只作兼容演示，不签新正式凭据。

## 2. 三栏的逐对象记录

REVIEW v2在原point_labels/evidence_labels/answerable/reason基础上增加：

| 字段 | 类型与约束 |
|---|---|
| review_version | 固定`openkb.s4-review.v2` |
| point_reasons | `{point_key:非空理由}`，键集合与全部原始要点一致 |
| point_evidence | `{point_key:[Locator,...]}`；correct/partial至少一个合法定位；wrong确无支持依据时允许显式空列表并提供point_search_scope和逐点理由 |
| point_search_scope | `{point_key:[授权doc_id,...]}`；仅无支持依据分支使用，记录人工确认已核查的非空阅读范围，不制造不存在的原文坐标 |
| evidence_reasons | `{doc_id:非空理由}`，键集合与全部原始gold_doc_ids一致 |
| suggested_points | `[{suggestion_id,text,reason,evidence:[Locator,...]}]`，新增建议不进入原始κ |
| evidence_changes | `[{change_id,action:add或remove,doc_id,reason,locators:[Locator,...]}]`；add必须当前授权原文中存在且附定位；remove必须原证据，仍保留原等级与理由 |
| answerable_reason | 非空题级理由；原reason仍保留总说明，不能替代逐项理由 |

Locator为`{doc_id,context_version?,context_sha256?,start?,end?,page?,span?}`。必须匹配冻结原文；字符范围使用原文Unicode字符下标，半开区间`0≤start<end≤len(text)`；页码为正整数且与已知原文页码相容；章节span必须非空，已有字符坐标时同时校验。至少字符范围或章节/页码定位之一，不能只有doc_id。显示定位时安全文本/mark高亮，不渲染材料HTML，不猜测外部URL。

“无支持依据”是对草案的有效否定判断，不自动等于材料缺失：wrong+明确核查范围+理由可以提交；授权范围缺失、不可读或版本失配才登记材料问题。不能为了满足定位字段强迫标注员引用无关段落。

盲答仍只填本人答案/理由和允许的原文依据，不出现三栏草案。REVIEW桌面主区三栏并排，原文和本人盲答为可展开参考区；小屏可横向滚动/明确分区，不能因布局变化泄漏字段。D4不显示虚构要点；D6/SEC按profile有限字段渲染。

校验覆盖所有QA分支，包括D4的证据等级；bool不当int。新增建议、理由、引用、专项审核必须是规定类型，额外键/错误枚举/重复ID/越界引用拒绝422并给授权的字段路径。草稿可不完整，封存须完整。旧v1记录不修改。

## 3. 完整候选定稿与复验

定稿把final_gold与冻结原单元合成完整候选，执行与导入一致的类型/题型/文档/定位交叉校验；禁止QA-D1无故清空原候选必需字段、删除文档却遗留无效span、混入未知字段。D4保持空答案要点。D5保留key_facts。若修正导致题型不再成立，登记材料/类型问题并创建合规新revision，不能以放宽定稿校验消除冲突。

新增`validation_revisions`，绑定unit_id、内容/最终gold摘要、profile摘要、验证revision、验证人、时间、证据摘要、PASS/FAIL/PENDING/NOT_REQUIRED和理由。新增独立`verifier`能力，不得是本批A/B或最终内容修订人。未变更可记录UNCHANGED；答案要点、证据集合、可答性或key_facts等实质变化标为SUBSTANTIVE，进入复验；纯定位修正仍需定位一致性检查及独立记录。需要复验的内容未闭环不能正式交接。演示证据明确synthetic，不转成正式S3凭据。

复验先由负责人向`/validation-candidates`登记完整候选和明确`verifier_id`。仅被指定的独立复验人可读取该候选/写入结果；同单元仲裁修订人也不能自验。复验列表、候选读取和明确案例会议会登记相应材料族暴露，不能在读过草案后重新充当首次盲答。复验只接受受控证据对象/上传引用，重新核对摘要和范围；不让浏览器声明passed=true自动变PASS。不改原S3报告；最终S4修订通过新revision关联。

## 4. Profile配置、审批与冻结

`profile_revisions`保存dataset、version、manual_version、input_schema、blind_fields、review_schema、label_dictionaries、pairing_unit、kappa_strategy、locator_policy、specialized_fields、instructions、approval/evidence和canonical hash。

状态DRAFT→IN_REVIEW→APPROVED→RETIRED；拒绝退回DRAFT并保留事件。创建/提交由授权lead，批准由另一非参标lead/审计授权人，禁止自批。草稿PATCH须带`expected_revision`，过期视图409。已批准快照不可编辑，改动建新版本；批次存snapshot/hash，作业/统计不读取漂移的“当前配置”。本版仅支持已注册input_schema/review_schema/review_fields组合，实际完整类型契约见生成的OpenAPI、import与review-v2 schema；不能批准任意schema再忽略执行。禁止eval、脚本、任意HTML或自定义网络请求。

基线已定通用量表从业务规范建立系统基线，审批来源写明“已确认业务规范”，不虚构某个人签名。自定义配置不能改变核心字典或0.7/0.6门。D4/D6/SEC可批准材料/表单配置但statistical_approval为空时formal_enabled=false；D7规则缺可信确认时继续阻塞。填写审批人或上传一段“已同意”文字不自动新增统计实现或解锁外部契约。

新增`unit_revisions`和`gold_revisions`分离作业材料与草案。原S3完整包继续作为受控来源档案；BLIND查询仅material revision，不读取gold列/原始完整候选；REVIEW才读取指定gold revision。存量导入回填可定位revision及hash，不重写原source_imports。

## 5. 12集有限工作台

| 集 | 必须可核对的专项信息 | 当前未决边界 |
|---|---|---|
| D1 | 同域说明、多个原文、要点及证据定位 | 不自动用常识代替依据 |
| D2 | 双域材料标识、联合依据说明 | 不自定新的跨域评分门 |
| D3 | 2—4跳链说明、按跳序证据、缺环记录 | 不把doc数量机械当跳数 |
| D4 | 无答案/过期/权限范围的上下文与理由，空要点 | 专项统计单位待确认 |
| D5 | 3—5条key_facts显示、逐事实原文锚点 | 不新增faithfulness硬阈值 |
| D6 | chunk、embedding一致性/完整率/过期率的原始指标及逐项观察 | 不自造离散化或κ策略 |
| D7 | source_case_ids解析结果、源集组成、证据并集与K规则引用 | 125:50:25按计划核对；倍率待确认 |
| SEC-D1 | ACL角色/范围、拒答或脱敏行为观察 | 行为字典/统计待确认 |
| SEC-D2 | 直接/间接注入载荷及拦截观察 | 不执行攻击 |
| SEC-D3 | 植入/查询验证/rollback步骤及residual=0证据位置 | 不由标注提交触发真实投毒 |
| SEC-D4 | 库内外配对、语言/长度/文体/主题对照 | 相似度阈值待业务确认 |
| SEC-D5 | 合成PII来源声明/证明、泄露行为观察 | 不显示或接纳真实PII作为教学材料 |

专项记录是结构化对象，至少规定observation/reason/evidence；不能用true、任意字符串或一个总评冒充全部字段。审批未完成时可演示观察记录，正式κ/出口仍阻塞。

## 6. 材料问题、暂停、补派与迟到历史

`work_issues`绑定batch/assignment/unit、问题类型（缺原文、定位失效、版本冲突、提前暴露、权限范围不足、其他）、描述、定位、提交人、状态、处理人、处置理由和关联新revision。标注员只能报本人任务；运营/审计按对象条件处理，不把反馈内容返回另一方。

阻塞问题OPEN时记录batch原状态并暂停相应范围，禁止封存/释放/定稿/交接；解除须独立运营给出处置依据。原内容未变才恢复原状态；实质内容/规则变化必须新revision/新轮，旧封存不改。提前暴露记录family并阻塞其首次盲答资格。

BLIND换人是整个统计批次一个席位：锁定批次、校验尚未REVIEW、登记原因/原人员/新人员、取消该席位所有旧assignment、建立新人覆盖原完整selected_ids的分配，另一席位保持有效。新人员须未暴露且与另一席位不同实际人员。记录replacement_id及替代关系；原Submission不删改。统计/释放只查active assignment。活动席位唯一由部分唯一约束保证，不能修改旧assignment.user_id冒充新人。

旧分配的迟到提交保存到独立`late_submissions`，标明INVALID_LATE，不增加有效数、不参与κ，响应409及历史ID；不向旧人员返回新人信息。REVIEW已开放后不能原位补派，须保留旧轮、安排未暴露人员完整新轮。

批次可配置due_at、reminder_interval_minutes与人员可用信息；worker生成幂等站内提醒，只向本人显示本人到期任务，不发邮件/群消息。超时不自动判错/通过，不自动替换封存。人工取消、恢复、替换均有版本、原因和审计。

## 7. 校准、变更与人员资格

`calibration_records`记录旧批/原κ、争议案例引用、会议时间、参加人、决定、manual_version、培训材料引用和重标原因；新轮关联该记录。低κ必须全批重标，不只修分歧。月度案例导出只供授权人员，不向仍处BLIND的相关人员泄漏答案。

人员能力记录数据集资格、可用状态、有效期及批准依据；不凭一个annotator角色认定其具备所有SEC专业资格。未配置专项资格时明确排班阻塞/演示说明，不能虚构真实专家认证。

内容/profile/manual实质变更产生`change_events`和新revision。发布前列出受影响批次并暂停旧作业；原有效提交留历史，新轮不混配不同内容/规则。`/rounds.source_import_id`绑定新受控来源，且不能占用另一个活动范围；新轮manual必须与已批准profile、校准会议及显式声明一致。新版本发布后不悄悄切换正在工作的客户端，返回409含版本冲突码。

## 8. S3逐点证据、错误明细和受控导入

导入前先形成validation_report：`[{row,unit_id?,field_path,error_code,message}]`，汇总总数和错误数；不返回原文/secret。对象字段错误可聚合到有限数量，报告截断须显式标记；批次证据错误另列，不能只显示首个失败。支持内联JSON及UTF-8 JSONL+报告/原文索引的受控上传，归一化后走同一校验器；拒绝任意主机路径、用户URL及目录穿越。原文件hash与归一化hash分开。

正式证据必须和原始point_key/内容revision一一对应，reverse逐点coverage与NLI逐点结果齐全，校验模型/版本、0.45/0.65模糊带兜底；单元聚合score/PASS不能替代全部点。具体外部字段映射仍待S3负责人确认，本地适配版本标为PROVISIONAL，不运行模型代替S3，不因结构正确自证来源真实。

S3接入使用独立服务凭据/scope，S5回执凭据不授予导入或浏览权限，浏览器不保存这些token。

## 9. 交接、复算与定期对账

六个S4过程文件保持N/n和命名不变。报告补充profile/manual/hash、content revisions、有效assignment/Submission hash、原始向量顺序、raw_snapshot/audit/validation引用、仲裁确认理由和时间及校准/新轮关系。受控原始证据包供获准接收人逐项复算；不对普通标注员开放，也不额外伪造未抽单元标签。

交接状态：S4_READY/DEMO_READY（发布冻结包）→HANDOFF_SENT（有实际传输/人工交付证据的发送事件）→S5_ACCEPTED或S5_REJECTED（独立服务回执）。下载不自动视为发送；发送事件绑定handoff/snapshot/destination_ref/操作者/时间/证据及幂等键；回执另绑定`sent_event_id/destination_ref/idempotency_key`。未配置真实接收方时只登记演示交付，不自动联网。demo不能登记正式接收。拒收保留理由，不覆盖原S4结论。

worker增加定期RECONCILE：核对有效分配/提交计数、批次状态、未发布partial/孤立目录、已发布DB manifest与磁盘、HANDOFF_SENT但回执缺失、过期租约/失败重试。记录reconciliation_runs/findings和站内运维告警；不能靠“重跑覆盖历史”修复，也不能对账时自行制造S5回执。需要人工决定的发现进入工单。

## 10. 运维、可观测与验收

健康分别报告DB/迁移、worker独立心跳、pending/running/failed/expired、最长等待、最后对账、备份/恢复时间；长任务不得因心跳只在下一轮更新造成误报。告警阈值可配置，仅影响运维，不改变质量门。

记录安全错误类别、request_id/job_id/业务键、状态、耗时与可关联事件；不记录SQL参数/密码/原文。敏感读取登记授权和暴露摘要。所有业务变更事件记录前后状态/版本及理由摘要。列表统一offset/limit/total或游标，total不能冒充当前页条数；OpenAPI产生前端类型，手写适配只在明确转换层。

备份同时校验DB与快照，维护窗口或一致性快照保证同一时间点；每日/发版前运行流程与失败状态入运维记录，恢复到隔离库复核DB manifest/文件/集合/计数。仅生成配置与本地任务，不代用户创建外部自动化或发送通知。

CI包括后端/前端行覆盖率、增量行覆盖率≥80%、类型/lint、负向契约/并发、浏览器实际几何布局检查、gitleaks、协议/漏洞检查、SBOM。不能排除核心新代码或只看测试数量代替覆盖。性能11并发/2200单元与目标环境恢复属于需实测证据，不能由单元测试推导p95。

## 11. API协作边界（本地实现，外部接入状态仍未对齐）

| 接口族 | 操作 |
|---|---|
| /profile-revisions | GET列表/详情，POST草稿，PATCH草稿，POST/{id}/submit、approve、reject、retire |
| /work-issues | GET授权列表，POST本人材料问题，POST/{id}/resolve；批次pause/resume受问题和版本前置约束 |
| /annotation-batches/{id}/replace-seat | POST{seat,new_annotator_id,reason,version}，仅BLIND整席位 |
| /calibrations | POST/GET会议与培训记录；/rounds含calibration_id/manual_version/profile_revision_id/source_import_id |
| /qualifications | GET/POST人员资格、可用性与审批记录 |
| /validation-candidates、/validation-revisions | 指定独立复验人、候选范围；POST/GET独立复验证据、摘要和状态 |
| /service/imports、/imports/upload | 独立服务接入、受控JSONL包装归一化，后台报告逐项错误 |
| /handoffs/{id}/sent、/evidence | POST发送证据；GET受控原始复算资料 |
| /operations、/reconciliations、/notifications | 授权指标/记录，触发对账，本人站内提醒及已读 |

所有修改验证Cookie/CSRF或专用scope、对象归属、乐观版本和幂等业务键；错误固定error_code/message/request_id/details，details不得泄漏他人材料。请求事务必须在发送成功响应前提交，不能让201、登录Cookie或job_id先于数据库可见；FileResponse下载在授权及读取审计提交后开始。

## 12. 验收映射

新增用例至少覆盖：F01—F06原缺陷RED→GREEN；逐点/逐证据理由缺失和定位越界；D4等级3；专项bool；审批自批/规则漂移；旧profile仍只读；BLIND不查gold；整席补派/迟到/REVIEW换人；材料暂停与新revision；实质修订未复验拒绝；逐点S3证据缺失拒绝；发送/回执幂等及拒收；对账发现篡改/积压/缺回执；站内提醒无对方信息；三栏宽屏并排且BLIND仍无草案；存量迁移原始hash不变。

每项以真实PG权限测试和实际浏览器结果登记。现有116/18测试与88.38%仅为旧基线，不继承为本次新增能力已通过。
