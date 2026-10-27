import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { LoginForm } from '../components/LoginForm';
import { ReviewForm } from '../components/ReviewForm';

describe('登录', () => {
  it('显示认证失败并允许修改密码重试，不把失败当作已登录', async () => {
    const submit = vi.fn().mockRejectedValue(new Error('账号或密码错误'));
    render(<LoginForm onLogin={submit} />);
    await userEvent.type(screen.getByLabelText('账号'), 'annotator-a');
    await userEvent.type(screen.getByLabelText('密码'), 'wrong-password');
    await userEvent.click(screen.getByRole('button', { name: '登录工作台' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('账号或密码错误');
    expect(screen.getByRole('button', { name: '登录工作台' })).toBeEnabled();
  });
});

describe('三栏复核', () => {
  it('按point_key和doc_id提交多项标签，并把相关度序列化为2/1/0数值', async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewForm points={[{ point_key: 'P001', text: '第一要点' }, { point_key: 'P002', text: '第二要点' }]} gold={{ answer_points: ['第一要点', '第二要点'], gold_doc_ids: ['doc-a', 'doc-b'], answerable: 'answerable' }} onSave={submit} onSubmit={submit} />);
    await userEvent.selectOptions(screen.getByLabelText('P001 正确性'), 'correct');
    await userEvent.selectOptions(screen.getByLabelText('P002 正确性'), 'partial');
    await userEvent.selectOptions(screen.getByLabelText('doc-a 相关度'), '2');
    await userEvent.selectOptions(screen.getByLabelText('doc-b 相关度'), '0');
    await userEvent.selectOptions(screen.getByLabelText('可答性'), 'answerable');
    await userEvent.type(screen.getByLabelText('复核理由'), '第二要点缺少限定条件，doc-b无关。');
    await userEvent.click(screen.getByRole('button', { name: '提交并封存复核' }));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ point_labels: { P001: 'correct', P002: 'partial' }, evidence_labels: { 'doc-a': 2, 'doc-b': 0 }, answerable: 'answerable' }));
    expect(screen.queryByRole('option', { name: /相关（3）/ })).not.toBeInTheDocument();
  });

  it('缺少原始要点或证据判定时拒绝封存', async () => {
    const submit = vi.fn().mockResolvedValue(undefined);
    render(<ReviewForm points={[{ point_key: 'P001', text: '原始要点' }]} gold={{ answer_points: ['原始要点'], gold_doc_ids: ['doc-a'], answerable: 'answerable' }} onSave={submit} onSubmit={submit} />);
    await userEvent.click(screen.getByRole('button', { name: '提交并封存复核' }));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('请完成每个原始要点、证据、可答性及理由');
  });
});
