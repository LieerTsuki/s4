import { useState } from 'react';
import { CheckCheck, Save } from 'lucide-react';
import type { Answerability, Gold, Point, PointLabel, ReviewPayload } from '../types';

export function ReviewForm({ points, gold, onSave, onSubmit, initial, disabled }: { points: Point[]; gold: Gold; onSave: (payload: ReviewPayload) => Promise<void>; onSubmit: (payload: ReviewPayload) => Promise<void>; initial?: Partial<ReviewPayload>; disabled?: boolean }) {
  const [pointLabels, setPointLabels] = useState<Record<string, PointLabel>>(initial?.point_labels ?? {});
  const [evidenceLabels, setEvidenceLabels] = useState<Record<string, number>>(initial?.evidence_labels ?? {});
  const [answerable, setAnswerable] = useState<Answerability | ''>(initial?.answerable ?? '');
  const [reason, setReason] = useState(initial?.reason ?? '');
  const [suggested, setSuggested] = useState(initial?.suggested_points?.join('\n') ?? '');
  const [changeAction, setChangeAction] = useState('add');
  const [changeDoc, setChangeDoc] = useState('');
  const [changeReason, setChangeReason] = useState('');
  const [changes, setChanges] = useState(initial?.evidence_changes ?? []);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const evidence = gold.gold_doc_ids ?? [];
  const payload = (): ReviewPayload => ({ point_labels: pointLabels, evidence_labels: evidenceLabels, answerable, reason: reason.trim(), suggested_points: suggested.split('\n').map(value => value.trim()).filter(Boolean), evidence_changes: changes });
  async function perform(seal: boolean) {
    setError(''); setSaved(false);
    if (seal && (!points.every(point => !!pointLabels[point.point_key]) || !evidence.every(id => evidenceLabels[id] !== undefined) || !answerable || !reason.trim())) { setError('请完成每个原始要点、证据、可答性及理由'); return; }
    setPending(true);
    try { await (seal ? onSubmit : onSave)(payload()); if (!seal) setSaved(true); }
    catch (failure) { setError(failure instanceof Error ? failure.message : '提交失败，请重试。'); }
    finally { setPending(false); }
  }
  return <form className="review-form" noValidate onSubmit={event => { event.preventDefault(); void perform(true); }}>
    <div className="review-columns">
      <section className="review-column"><div className="section-eyebrow">01 · 答案要点</div><h3>逐点核对正确性</h3><p className="muted">保留原始要点，对每项独立作出判断。</p>{points.length ? points.map(point => <div className="label-card" key={point.point_key}><span className="mono tiny">{point.point_key}</span><p>{point.text}</p><select aria-label={`${point.point_key} 正确性`} value={pointLabels[point.point_key] ?? ''} disabled={disabled} onChange={event => setPointLabels({ ...pointLabels, [point.point_key]: event.target.value as PointLabel })}><option value="">请选择判定</option><option value="correct">正确</option><option value="partial">部分正确</option><option value="wrong">错误</option></select></div>) : <p className="empty-inline">该任务没有答案要点，不生成虚构判定。</p>}
        <label htmlFor="suggested-points">补充遗漏要点（每行一条）</label><textarea id="suggested-points" rows={3} value={suggested} onChange={event => setSuggested(event.target.value)} disabled={disabled} placeholder="仅作为修订建议，不改写原始统计对象" />
      </section>
      <section className="review-column"><div className="section-eyebrow">02 · 证据相关度</div><h3>逐文档确认依据</h3><p className="muted">使用文档标识绑定等级，相关度仅为2 / 1 / 0。</p>{evidence.length ? evidence.map(doc => <div className="label-card" key={doc}><span className="mono">{doc}</span><select aria-label={`${doc} 相关度`} value={evidenceLabels[doc] ?? ''} disabled={disabled} onChange={event => { if (event.target.value === '') { const next = { ...evidenceLabels }; delete next[doc]; setEvidenceLabels(next); } else setEvidenceLabels({ ...evidenceLabels, [doc]: Number(event.target.value) }); }}><option value="">请选择相关度</option><option value="2">相关（2）</option><option value="1">部分相关（1）</option><option value="0">不相关（0）</option></select></div>) : <p className="empty-inline">该任务无原始证据项。</p>}
        <details><summary>建议增删证据</summary><div className="form-stack"><select aria-label="证据变更类型" value={changeAction} onChange={event => setChangeAction(event.target.value)} disabled={disabled}><option value="add">建议新增</option><option value="remove">建议删除</option></select><input aria-label="变更文档标识" value={changeDoc} onChange={event => setChangeDoc(event.target.value)} placeholder="doc_id" disabled={disabled} /><input aria-label="证据变更理由" value={changeReason} onChange={event => setChangeReason(event.target.value)} placeholder="变更理由" disabled={disabled} /><button className="button small" type="button" disabled={disabled || !changeDoc.trim() || !changeReason.trim()} onClick={() => { setChanges([...changes, { action: changeAction, doc_id: changeDoc.trim(), reason: changeReason.trim() }]); setChangeDoc(''); setChangeReason(''); }}>加入建议</button></div></details>
        {changes.map((change, index) => <div className="suggestion" key={`${change.doc_id}-${index}`}>{change.action === 'add' ? '新增' : '删除'} {change.doc_id} · {change.reason}<button type="button" className="text-button" disabled={disabled} onClick={() => setChanges(changes.filter((_, current) => current !== index))}>移除建议</button></div>)}
      </section>
      <section className="review-column"><div className="section-eyebrow">03 · 可答性</div><h3>核对回答边界</h3><p className="muted">结合原文范围、时效与权限判断。</p><label htmlFor="answerability">可答性</label><select id="answerability" value={answerable} disabled={disabled} onChange={event => setAnswerable(event.target.value as Answerability)}><option value="">请选择</option><option value="answerable">answerable · 可回答</option><option value="no_answer">no_answer · 无答案</option><option value="expired">expired · 已过期</option><option value="out_of_scope">out_of_scope · 范围外</option></select><label htmlFor="review-reason">复核理由</label><textarea id="review-reason" rows={8} value={reason} disabled={disabled} onChange={event => setReason(event.target.value)} placeholder="写明原文依据与判断理由；存在多种不可答原因时说明冲突" /></section>
    </div>
    {error && <div role="alert" className="notice danger">{error}</div>}{saved && <div role="status" className="notice success">草稿已保存，尚未计入正式提交。</div>}
    <div className="form-footer"><span className="muted">正式提交将封存本轮判断，后续修订保留历史。</span><div className="button-row"><button type="button" className="button" disabled={disabled || pending} onClick={() => void perform(false)}><Save size={16} />暂存草稿</button><button type="submit" className="button primary" disabled={disabled || pending}><CheckCheck size={16} />{pending ? '正在提交…' : '提交并封存复核'}</button></div></div>
  </form>;
}
