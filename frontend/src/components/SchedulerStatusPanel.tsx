import type {SystemHealth} from "../services/healthService";

export default function SchedulerStatusPanel({health}:{health:SystemHealth}) {
  const rows = health.recentTaskRuns ?? [];
  return <section className="panel">
    <div className="panel-heading"><div><h2>Scheduler Status</h2><p>最近任务运行记录，失败任务不会生成假推荐。</p></div></div>
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Task</th><th>Status</th><th>Attempts</th><th>Started</th><th>Finished</th><th>Warnings</th></tr></thead>
      <tbody>{rows.length?rows.map(row=><tr key={row.id}><td>{row.task_name}</td><td>{row.status}</td><td>{row.attempts}</td><td>{new Date(row.started_at).toLocaleString("zh-CN")}</td><td>{row.finished_at?new Date(row.finished_at).toLocaleString("zh-CN"):"-"}</td><td>{row.warnings?.join("; ") || row.error_message || "-"}</td></tr>):<tr><td colSpan={6}>暂无任务记录</td></tr>}</tbody></table></div>
  </section>;
}
