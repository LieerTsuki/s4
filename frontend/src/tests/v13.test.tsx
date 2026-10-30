import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ReviewV3Form } from "../v13/ReviewV3Form";
import { ExtractionEditor } from "../v13/ExtractionEditor";
import { codePointRange } from "../v13/unicode";
import { ProgressSummary } from "../v13/Pages";

describe("v1.3 全量核实与观测", () => {
  it("全量未核实数独立于观测数量，不把8条观测冒充12条核实", () => {
    render(<ProgressSummary report={{ N: 12, verified_count: 8, n: 8, observation_pairs: 8, blocked_reasons: ["WAITING_VERIFICATION"] }} />);
    expect(screen.getByText("待核实 4 条")).toBeInTheDocument();
    expect(screen.getByText("观测单元 n = 8")).toBeInTheDocument();
  });

  it("三栏把拒答保存为boolean，将证据判定0..3与最终gold分开", async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewV3Form dataset="QA-D4C" points={[]} gold={{ gold_doc_ids: ["doc-a"], relevance_grades: { "doc-a": 3 }, ranking_annotations: {}, expected_refusal: false }} contexts={[{doc_id:"doc-a",text:"授权原文"}]} initial={{ evidence_assessments: {"doc-a": {grade: 1,reason: "仅背景相关",locators:[],intent: "MOVE_TO_RANKING"}}, expected_refusal:false, expected_refusal_reason:"可依据原文作答", reason:"已逐条核实", verdict:"NEEDS_REVISION" }} onSave={submit} onSubmit={submit} />);
    expect(screen.getAllByRole("heading", {level:3})).toHaveLength(3);
    expect(document.querySelector(".review-columns")?.children).toHaveLength(3);
    expect(screen.queryByRole("option", {name:"权限范围外"})).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", {name:"提交并封存核实"}));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ expected_refusal:false, absence_reason:null, evidence_assessments:{"doc-a":expect.objectContaining({grade:1,intent:"MOVE_TO_RANKING"})} }));
  });

  it("D4只允许拒答并要求三种原因之一", async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewV3Form dataset="QA-D4" points={[]} gold={{gold_doc_ids:[],relevance_grades:{},ranking_annotations:{},expected_refusal:true}} contexts={[]} initial={{ reason:"已查全部授权材料", expected_refusal_reason:"库内无答案" }} onSave={submit} onSubmit={submit} />);
    expect(screen.getByLabelText("预期拒答")).toBeDisabled();
    await userEvent.click(screen.getByRole("button", {name:"提交并封存核实"}));
    expect(submit).not.toHaveBeenCalled();
    await userEvent.selectOptions(screen.getByLabelText("拒答原因"), "库内无答案");
    await userEvent.click(screen.getByRole("button", {name:"提交并封存核实"}));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ expected_refusal:true,absence_reason:"库内无答案" }));
  });

  it("D6用Unicode码点坐标，删除实体同时移除悬空关系", async () => {
    expect(codePointRange("甲😀乙", 1, 3)).toEqual([1,2]);
    const change=vi.fn();
    render(<ExtractionEditor text="甲😀乙" vocabulary={{entity_types:["PERSON","OTHER"],relation_types:["OTHER_REL"],version:"fixture-v1",sha256:"a".repeat(64)}} value={{gold_entities:[{entity_id:"e1",name:"甲",type:"PERSON",span:[0,1]},{entity_id:"e2",name:"乙",type:"PERSON",span:[2,3]}],gold_relations:[{head:"e1",tail:"e2",type:"OTHER_REL"}]}} onChange={change} />);
    await userEvent.click(screen.getByRole("button", {name:"删除实体 e1"}));
    expect(change).toHaveBeenCalledWith({ gold_entities:[{entity_id:"e2",name:"乙",type:"PERSON",span:[2,3]}],gold_relations:[] });
  });
  it("新版遗漏与证据变更建议单独留痕，不覆盖原对象判断", async () => {
    const save=vi.fn().mockResolvedValue(undefined);
    render(<ReviewV3Form dataset="QA-D1" points={[]} gold={{gold_doc_ids:[],ranking_annotations:{}}} contexts={[{doc_id:"doc-a",text:"原文依据"}]} onSave={save} onSubmit={save}/>);
    await userEvent.click(screen.getByRole("button",{name:"新增遗漏要点建议"}));
    await userEvent.type(screen.getByLabelText("遗漏要点 1"),"补充限定条件");
    await userEvent.type(screen.getByLabelText("遗漏理由 1"),"原草案缺少范围限制");
    await userEvent.click(screen.getByRole("button",{name:"新增证据变更建议"}));
    await userEvent.selectOptions(screen.getByLabelText("证据变更文档 1"),"doc-a");
    await userEvent.type(screen.getByLabelText("证据变更理由 1"),"需要引用该原文");
    await userEvent.click(screen.getByRole("button",{name:"保存核实草稿"}));
    expect(save).toHaveBeenCalledWith(expect.objectContaining({verdict:"NEEDS_REVISION",point_labels:{},suggested_points:[expect.objectContaining({text:"补充限定条件",reason:"原草案缺少范围限制"})],evidence_changes:[expect.objectContaining({action:"add",doc_id:"doc-a",reason:"需要引用该原文"})]}));
  });
  it("从真实表单完成逐点、逐文档定位和布尔拒答再封存",async()=>{
    const submit=vi.fn().mockResolvedValue(undefined);
    render(<ReviewV3Form dataset="QA-D1" points={[{point_key:"P001",text:"四日办理"}]} gold={{gold_doc_ids:["doc-a"],relevance_grades:{"doc-a":3},ranking_annotations:{},expected_refusal:false}} contexts={[{doc_id:"doc-a",text:"四日办理",sha256:"a".repeat(64)}]} onSave={submit} onSubmit={submit}/>);
    await userEvent.selectOptions(screen.getByLabelText("P001 正确性"),"correct");
    await userEvent.type(screen.getByLabelText("P001 理由"),"原文直接支持");
    await userEvent.type(screen.getByLabelText("P001 定位 起点"),"0");
    await userEvent.type(screen.getByLabelText("P001 定位 终点"),"4");
    await userEvent.click(screen.getByRole("button",{name:"加入P001 定位"}));
    await userEvent.type(screen.getByLabelText("doc-a 理由"),"直接含答案");
    await userEvent.type(screen.getByLabelText("doc-a 证据定位 起点"),"0");
    await userEvent.type(screen.getByLabelText("doc-a 证据定位 终点"),"4");
    await userEvent.click(screen.getByRole("button",{name:"加入doc-a 证据定位"}));
    await userEvent.selectOptions(screen.getByLabelText("预期拒答"),"false");
    await userEvent.type(screen.getByLabelText("预期拒答判断理由"),"可答");
    await userEvent.type(screen.getByLabelText("核实说明"),"全量核实完成");
    await userEvent.click(screen.getByRole("button",{name:"提交并封存核实"}));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({point_labels:{P001:"correct"},point_evidence:{P001:[expect.objectContaining({start:0,end:4,context_sha256:"a".repeat(64)})]},expected_refusal:false,absence_reason:null,evidence_assessments:{"doc-a":expect.objectContaining({grade:3,intent:"KEEP_GOLD"})}}));
  });
  it("错误点明确登记无支持检索范围并保存移动证据建议",async()=>{
    const submit=vi.fn().mockResolvedValue(undefined);
    render(<ReviewV3Form dataset="QA-D1" points={[{point_key:"P001",text:"错误草案"}]} gold={{gold_doc_ids:["doc-a"],relevance_grades:{"doc-a":3},ranking_annotations:{}}} contexts={[{doc_id:"doc-a",text:"不支持草案"}]} onSave={submit} onSubmit={submit}/>);
    await userEvent.selectOptions(screen.getByLabelText("P001 正确性"),"wrong");
    await userEvent.type(screen.getByLabelText("P001 理由"),"已核完整材料，无支持");
    await userEvent.click(screen.getByRole("checkbox",{name:"doc-a"}));
    await userEvent.selectOptions(screen.getByLabelText("doc-a 相关度"),"0");
    await userEvent.selectOptions(screen.getByLabelText("doc-a 处理建议"),"MOVE_TO_RANKING");
    await userEvent.type(screen.getByLabelText("doc-a 理由"),"易混淆弱相关");
    await userEvent.selectOptions(screen.getByLabelText("预期拒答"),"true");
    await userEvent.selectOptions(screen.getByLabelText("拒答原因"),"库内无答案");
    await userEvent.type(screen.getByLabelText("预期拒答判断理由"),"材料未找到答案");
    await userEvent.selectOptions(screen.getByLabelText("核实结论"),"NEEDS_REVISION");
    await userEvent.click(screen.getByRole("button",{name:"提交并封存核实"}));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({point_labels:{P001:"wrong"},point_evidence:{P001:[]},point_search_scope:{P001:["doc-a"]},expected_refusal:true,absence_reason:"库内无答案",verdict:"NEEDS_REVISION"}));
  });
});
