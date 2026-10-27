import { ArrowUpRight, CheckCheck, FileStack, Layers3, LockKeyhole, Route, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useList } from '../hooks';
import type { AnnotationBatch, ImportRecord, Task, User } from '../types';
import { Badge, Empty, ErrorNotice, PageHeader, PageLink, Panel } from '../components/Common';

export function Dashboard({ user }: { user: User }) {
  const manage = user.roles.some(role => ['lead','auditor','arbitrator'].includes(role));
  const annotate = user.roles.includes('annotator');
  const batches = useList<AnnotationBatch>('/annotation-batches', manage);
  const canReadImports = user.roles.some(role => ['lead','auditor'].includes(role)); const imports = useList<ImportRecord>('/imports', canReadImports);
  const tasks = useList<Task>('/me/tasks', annotate);
  const batchItems = batches.data?.items ?? []; const taskItems = tasks.data?.items ?? [];
  return <><PageHeader eyebrow="ANNOTATION & QUALITY CONTROL" title="让每一次判断，都有据可循。" description={`你好，${user.display_name}。从独立作答开始，留下可复算、可追溯的质量记录。`} action={<span className="workspace-date">{new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: 'long', day: 'numeric' }).format(new Date())}</span>} />
    <div className="overview-banner"><div className="banner-symbol"><ShieldCheck size={32} strokeWidth={1.4} /></div><div><div className="section-eyebrow">INDEPENDENT S4 WORKSPACE</div><h2>独立双盲 · 原始判断封存 · 质量闭环</h2><p>先独立作答，再统一开放草案。双方结果相互隔离，批次结论保留原始依据。</p></div><div className="banner-status"><span className="status-dot" />外部接口待对齐<span className="tiny muted">本地验证与生产验收分别记录</span></div></div>
    <div className="stats-grid">
      {manage && <>{canReadImports && <div className="stat-card"><div><span>候选导入</span><FileStack size={19} /></div><strong>{imports.data ? imports.data.total : '—'}</strong><p>已登记来源批次</p></div>}<div className="stat-card"><div><span>标注批次</span><Layers3 size={19} /></div><strong>{batches.data ? batches.data.total : '—'}</strong><p>冻结人员对与统计范围</p></div><div className="stat-card"><div><span>内容已定稿</span><CheckCheck size={19} /></div><strong>{batches.data ? batchItems.filter(batch => batch.finalized).length : '—'}</strong><p>当前列表中的已定稿批次</p></div></>}
      {annotate && <div className="stat-card"><div><span>我的任务</span><LockKeyhole size={19} /></div><strong>{tasks.data ? tasks.data.total : '—'}</strong><p>仅展示分配给本人的任务</p></div>}
      {!manage && !annotate && <div className="stat-card"><div><span>工作职责</span><ShieldCheck size={19} /></div><strong className="stat-text">账号与配置</strong><p>管理员不默认读取业务内容</p></div>}
      <div className="stat-card rule-stat"><div><span>批次质量门</span><Route size={19} /></div><strong>κ ≥ 0.7</strong><p>0.6≤κ&lt;0.7仲裁 · κ&lt;0.6整批重标</p></div>
    </div>
    <ErrorNotice error={batches.error ?? imports.error ?? tasks.error} />
    <div className="dashboard-grid"><Panel title={annotate ? '我的作业入口' : manage ? '最近标注批次' : '管理入口'} description={annotate ? '依照阶段完成作业，草稿与正式提交分开记录。' : '按实际记录展示进度，未完成项目保留等待状态。'} action={<PageLink to={annotate ? '/tasks' : manage ? '/batches' : '/users'}>查看全部</PageLink>}>
      {annotate ? taskItems.length ? <div className="list-rows">{taskItems.slice(0, 5).map(task => <Link className="record-row" to={`/tasks/${task.id}`} key={task.id}><div><strong>{task.unit_id}</strong><span>{task.dataset} · {task.batch_id}</span></div><Badge value={task.phase} /><ArrowUpRight size={16} /></Link>)}</div> : <Empty title="当前没有分配给你的任务" description="运营分配后，你可以在这里独立作答。" /> : manage ? batchItems.length ? <div className="list-rows">{batchItems.slice(0,5).map(batch => <Link key={batch.id} className="record-row" to={`/batches/${batch.id}`}><div><strong>{batch.dataset}</strong><span>{batch.id} · 第{batch.round}轮</span></div><Badge value={batch.state} /><ArrowUpRight size={16} /></Link>)}</div> : <Empty title="从第一个批次开始" description="导入候选材料，冻结抽样与人员后开始双盲作业。" action={user.roles.includes('lead') ? <Link className="button primary" to="/imports">导入候选材料</Link> : undefined} /> : <div className="quick-links"><Link to="/users"><strong>账号与角色</strong><span>创建、停用及重置工作账号</span><ArrowUpRight size={18} /></Link><Link to="/profiles"><strong>任务配置</strong><span>查看十二类任务及规则状态</span><ArrowUpRight size={18} /></Link><Link to="/health"><strong>运行状态</strong><span>检查数据库与worker就绪情况</span><ArrowUpRight size={18} /></Link></div>}
    </Panel><Panel title="作业流程" description="各阶段推进均由服务端核查。"><ol className="process-steps"><li><span>01</span><div><strong>材料与范围冻结</strong><p>版本、抽样、固定双人一并留痕</p></div></li><li><span>02</span><div><strong>独立作答并封存</strong><p>不见草案，不见另一方结果</p></div></li><li><span>03</span><div><strong>统一开放三栏复核</strong><p>全批盲答齐备后释放同版本草案</p></div></li><li><span>04</span><div><strong>质量判定与内容定稿</strong><p>保留原κ，完成仲裁或全批重标</p></div></li><li><span>05</span><div><strong>全量与抽检分别交付</strong><p>摘要核对后发布只读结果快照</p></div></li></ol></Panel></div>
  </>;
}
