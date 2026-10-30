# OpenKB-Eval S4 人工核实与质量观测系统

研发目录：`D:\openkb-eval\liyue\s4`。当前需求入口为上级 `document/00_v1.3执行入口与文档索引.md`，配套01 V0.7、07 V3.0、08 V2.0、09 V1.0。语源和两个旧管线不接入。

主线为 **S3有效候选 → N条全量人工核实 → S5独立验收**。另按数据集与难度抽样 `max(8,ceil(0.1*N_dataset))` 做固定双人观测；N不足8如实登记缺口。观测记录不能替代全量核实记录。13类目标为QA1700+SEC600=2300单元。

新版接口使用 `/api/s4/v2`，过程协议为 `openkb.s4-review.v3`，认证和账号继续使用v1接口。旧v1业务默认只读，原封存、标签和报告保持历史语义；不得自动换算旧等级或把历史n条抽检算成N条核实。`S4_LEGACY_WRITES_ENABLED=true`只用于隔离的历史回归环境。

## 运行

默认同源入口 [http://localhost:8084](http://localhost:8084)。源码变化须经过备份、隔离迁移演练和重建后才会出现在容器入口；以实际健康检查和本轮验收证据为准。

```powershell
Set-Location D:\openkb-eval\liyue\s4
docker compose --env-file .env -f deploy/compose.yml up -d --build --wait
```

API和worker共享受控文件卷，数据库只允许内部访问；开发数据库额外使用`compose.dev.yml`的本机55434端口。现有`.env`及数据库密码保持原样，不在聊天、日志或仓库中公开。HTTPS环境配置实际`S4_PUBLIC_ORIGIN`和`S4_COOKIE_SECURE=true`。

没有默认账号或公共注册。首次无账号时，在本机终端隐藏输入密码：

```powershell
docker compose --env-file .env -f deploy/compose.yml exec api python -m openkb_s4.cli bootstrap --username admin --display-name 系统管理员 --person-id YOUR-ACTUAL-PERSON-ID
```

管理员创建独立运营、主核实人员、两位观测人员及所需独立复验员；person_id对应真实人员。导入者已接触草案，不能成为同族材料首次盲答人员；受信管理员不兼任隔离盲答员。

## 新版操作

1. 在新版接入页导入`contracts/v13/examples/demo-import.json`结构的合成数据或已协商的真实v2数据。核验原始S3总体通过率和最终PASS集合，不能洗分母；正式协议仍标未对齐。
2. 建立覆盖N条的全量核实计划，另建固定A/B的观测计划，冻结种子和版本。两类任务分账，不事后复用主核实记录凑双人观测。
3. 主核实人员独立判断并封存后，按本人同源族屏障释放草案；观测须全统计批A/B独立封存后统一释放。
4. QA三栏分别核实答案要点、gold3/2与ranking1/0分区、布尔拒答和受控原因。难度保存easy/medium/hard；D6/SEC使用专项表单。
5. κ≥0.7记NORMAL，灰区扩样/校准，κ<0.6整批退S2；空向量、pe=1或专项统计未定为null。κ不替代N条核实，J1/C1冲突与正式适用规则显式保留。
6. 材料问题暂停任务；实质修订走独立复验，原来源和原提交不回写。全量核实、观测、问题和最终revision对账后输出演示过程包。
7. 新过程包含N候选、N核实、n观测和IAA、报告、质量动作及manifest。它不替代S5最终六文件；下载、真实发送和接收分别登记，尚不生成正式接收或HF发布。

## 数据与验证边界

新版正文、gold、草稿、提交、修订和观测向量在受控内容寻址文件中；DB只保留引用、摘要与必要运营索引。旧库历史正文暂保留只读；后续物理外置需备份核对和审核过的迁移，不能声称旧31张表已全部去正文。

PostgreSQL暂作本地运营索引。主仓builder/typer/SQLite真实Schema及GitLab五项权威门禁尚未提供，不能虚构映射或声称已集成。D6新版词表、SEC-D2类型字典、S3/S5协议、J1/C1裁决和真人验收仍是依赖。

验证、迁移与恢复见[新版运维手册](docs/operations-v13.md)，实现边界见[v1.3迁移契约](docs/specs/2026-10-30-s4-v13-migration.md)。2026-10-28验收仅证明当时0003/REVIEW v2，不作为新版测试结果。
