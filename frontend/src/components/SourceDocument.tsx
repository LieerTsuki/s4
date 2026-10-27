import { BookOpen } from 'lucide-react';
import type { ContextDocument } from '../types';
import { safeText } from '../format';

const fields = [
  ['valid_from', '有效起始'], ['valid_until', '有效截止'], ['version', '文档版本'],
  ['page', '页码'], ['start', '起始位置'], ['end', '终止位置'], ['acl_context', '权限背景'],
  ['license', '许可'], ['source_url', '来源地址'], ['sha256', '原文SHA-256'],
] as const;

export function SourceDocument({ document, open = false }: { document: ContextDocument; open?: boolean }) {
  const metadata = fields.filter(([key]) => document[key] != null);
  return <details className="context-document" open={open}><summary><BookOpen size={16} /><strong>{document.title ?? document.doc_id}</strong><span className="mono tiny">{document.doc_id}</span></summary>{metadata.length > 0 && <dl className="document-metadata">{metadata.map(([key, title]) => <div key={key}><dt>{title}</dt><dd>{safeText(document[key])}</dd></div>)}</dl>}<pre className="source-text">{document.text}</pre></details>;
}
