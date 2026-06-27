import {useEffect, useMemo, useState} from "react";
import PageHeader from "../components/PageHeader";
import useApi from "../hooks/useApi";
import useOfficialMatches from "../hooks/useOfficialMatches";
import {fetchSystemHealth, latestTaskRunByName, type SystemHealth} from "../services/healthService";

type AgentStep = {id: number; agent_name: string; status: string; error_message: string | null; started_at: string; finished_at: string | null; output: Record<string, unknown>};
type AgentRun = {id: string; status: string; trigger_name: string; started_at: string; finished_at: string | null; summary: Record<string, unknown>; steps: AgentStep[]};
type AgentStatus = {qwen: {configured: boolean; provider: string; model: string; base_host: string}; runs: AgentRun[]};
type TaskRun = NonNullable<SystemHealth["recentTaskRuns"]>[number];
type WorkflowItem = {task: string; title: string; description: string; dependsOn?: string};

const WORKFLOW: WorkflowItem[] = [
  {task: "official_sp_sync", title: "官方赛事/SP", description: "中国竞彩网赛事池、状态、官方赔率"},
  {task: "historical_data_sync", title: "历史库扩充", description: "联赛、全球、国家队历史 CSV 增量归档", dependsOn: "official_sp_sync"},
  {task: "external_odds_news_weather_sync", title: "外部赔率/新闻/天气", description: "The Odds API、新闻、天气与场地元数据", dependsOn: "official_sp_sync"},
  {task: "feature_build", title: "球队特征", description: "历史样本、Elo、lambda、source confidence", dependsOn: "historical_data_sync"},
  {task: "prospective_research_capture", title: "前瞻研究归档", description: "冻结模型、小时赔率与不可覆盖赛前预测", dependsOn: "feature_build"},
  {task: "qwen_news_analysis", title: "Qwen 情报", description: "新闻摘要、伤停与上下文因子", dependsOn: "external_odds_news_weather_sync"},
  {task: "backtest_run", title: "自动回测", description: "默认 CSV 回测与指标落库", dependsOn: "feature_build"},
  {task: "model_governance_check", title: "模型治理", description: "Champion/Challenger 检查，不自动替换模型", dependsOn: "backtest_run"},
];

const taskLabel: Record<TaskRun["status"], string> = {SUCCESS: "完成", FAILED: "失败", RUNNING: "运行中", SKIPPED: "跳过"};
const fmt = (value?: string | null) => value ? new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
}).format(new Date(value)) : "-";
const duration = (row?: TaskRun) => {
  if (!row?.finished_at) return row?.status === "RUNNING" ? "运行中" : "-";
  const ms = Date.parse(row.finished_at) - Date.parse(row.started_at);
  return Number.isFinite(ms) ? `${Math.max(0, Math.round(ms / 1000))} 秒` : "-";
};
const statusClass = (status?: TaskRun["status"]) => status === "SUCCESS" ? "running" : status === "FAILED" ? "alert" : status === "RUNNING" ? "delayed" : "finished";
const statusText = (status?: TaskRun["status"]) => status ? taskLabel[status] : "等待";
const outputSummary = (row?: TaskRun) => {
  if (!row) return "尚未运行";
  if (row.error_message) return row.error_message;
  const parts = [
    `影响 ${row.affected_matches ?? 0} 场`,
    `快照 ${row.created_snapshots ?? 0}`,
    `预测 ${row.created_predictions ?? 0}`,
  ];
  if (row.warnings?.length) parts.push(`警告 ${row.warnings.length}`);
  return parts.join(" / ");
};

function WorkflowGraph({tasks}:{tasks: Map<string, TaskRun>}) {
  return <div className="workflow-scroll">
    <div className="workflow-graph">
      {WORKFLOW.map((item, index) => {
        const row = tasks.get(item.task);
        return <div className="workflow-segment" key={item.task}>
          <article className={`workflow-node ${item.task === "model_governance_check" ? "critic" : ""}`}>
            <i>{index + 1}</i>
            <b>{item.title}</b>
            <small>{statusText(row?.status)} · {row?.status === "RUNNING" ? "开始时间" : "完成时间"} {fmt(row?.status === "RUNNING" ? row.started_at : row?.finished_at)}</small>
          </article>
          {index < WORKFLOW.length - 1 && <span className="workflow-arrow">→</span>}
        </div>;
      })}
    </div>
  </div>;
}

function TaskCards({tasks}:{tasks: Map<string, TaskRun>}) {
  return <div className="agent-card-grid" style={{padding: 16}}>
    {WORKFLOW.map(item => {
      const row = tasks.get(item.task);
      const progress = row?.status === "SUCCESS" ? 100 : row?.status === "RUNNING" ? 60 : row?.status === "FAILED" ? 100 : 0;
      return <article className="agent-status-card" key={item.task}>
        <div className="agent-card-head">
          <span className="agent-avatar">{item.title.slice(0, 1)}</span>
          <div><h3>{item.title}</h3><span className={`status-tag ${statusClass(row?.status)}`}>{statusText(row?.status)}</span></div>
        </div>
        <p style={{color: "var(--muted)", fontSize: 10, minHeight: 30}}>{item.description}</p>
        <div className="agent-progress"><div><span>完成度</span><b>{progress}%</b></div><div className="progress-track"><i style={{width: `${progress}%`}}/></div></div>
        <div className="agent-card-meta"><span>{duration(row)}</span><span>{fmt(row?.started_at)}</span><span>{item.dependsOn ? "依赖上游" : "入口"}</span></div>
      </article>;
    })}
  </div>;
}

export default function AgentMonitorPage() {
  const {matches, loading, error} = useOfficialMatches();
  const agentStatus = useApi<AgentStatus>("/api/agents/status", {qwen: {configured: false, provider: "", model: "", base_host: ""}, runs: []});
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [running, setRunning] = useState(false), [message, setMessage] = useState("");

  const refreshHealth = () => fetchSystemHealth().then(setHealth);
  useEffect(() => { void refreshHealth(); const timer = window.setInterval(refreshHealth, 30_000); return () => window.clearInterval(timer); }, []);

  const tasks = useMemo(() => latestTaskRunByName(health?.recentTaskRuns ?? []), [health]);
  const latestManual = agentStatus.data.runs[0];
  const blocked = matches.filter(match => !match.prediction.criticReport.passed);
  const done = WORKFLOW.filter(item => tasks.get(item.task)?.status === "SUCCESS").length;
  const failed = WORKFLOW.filter(item => tasks.get(item.task)?.status === "FAILED").length;
  const runningCount = WORKFLOW.filter(item => tasks.get(item.task)?.status === "RUNNING").length;

  const runAgents = async () => {
    setRunning(true); setMessage("正在运行完整 Agent 链路...");
    try {
      const response = await fetch("/api/agents/run", {method: "POST"});
      if (!response.ok) throw new Error(await response.text());
      const run = await response.json() as AgentRun;
      setMessage(`运行完成：${run.status}，共 ${run.steps.length} 个步骤。`);
      agentStatus.reload();
      void refreshHealth();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Agent 运行失败"); }
    finally { setRunning(false); }
  };

  return <div className="page">
    <PageHeader title="Agent / Workflow 监控" subtitle="自动化后台服务链路、每一步状态、最近运行记录与 Critic 诊断" />
    <section className="panel" style={{marginBottom: 16}}>
      <div className="panel-heading">
        <div><h2>自动化服务工作链路</h2><p>服务启动后立即执行一次，之后每小时执行；每一步都写入 task_runs。</p></div>
        <button onClick={() => void refreshHealth()}>刷新状态</button>
      </div>
      <section className="summary-strip" style={{padding: 16, margin: 0}}>
        <span>链路步骤<b>{WORKFLOW.length}</b></span>
        <span>已完成<b>{done}</b></span>
        <span>运行中<b>{runningCount}</b></span>
        <span>失败<b>{failed}</b></span>
        <span>Qwen<b>{agentStatus.data.qwen.configured ? "已配置" : "未配置"}</b></span>
        <span>前瞻研究<b>{health?.prospectiveResearch?.status ?? "未注册"}</b></span>
      </section>
      <WorkflowGraph tasks={tasks}/>
      <TaskCards tasks={tasks}/>
    </section>

    <section className="panel" style={{marginBottom: 16}}>
      <div className="panel-heading"><div><h2>前瞻确认研究</h2><p>算法冻结后只追加赛前预测；达到注册样本与时间门槛后仅检验一次。</p></div></div>
      <section className="summary-strip" style={{padding: 16, margin: 0}}>
        <span>状态<b>{health?.prospectiveResearch?.status ?? "NOT_REGISTERED"}</b></span>
        <span>不可变预测<b>{health?.prospectiveResearch?.predictions ?? 0}</b></span>
        <span>已结算比赛<b>{health?.prospectiveResearch?.settledMatches ?? 0}</b></span>
        <span>剩余样本<b>{health?.prospectiveResearch?.remainingMatches ?? 0}</b></span>
        <span>剩余天数<b>{health?.prospectiveResearch?.remainingDays ?? 0}</b></span>
        <span>确认结论<b>{health?.prospectiveResearch?.confirmationDecision ?? "尚未执行"}</b></span>
      </section>
    </section>

    <section className="panel" style={{marginBottom: 16}}>
      <div className="panel-heading"><div><h2>自动任务最近记录</h2><p>来自 /health.recentTaskRuns，显示后台任务是否完成。</p></div></div>
      <div className="table-scroll"><table className="data-table"><thead><tr><th>步骤</th><th>状态</th><th>开始</th><th>完成</th><th>耗时</th><th>产出 / 错误</th></tr></thead>
        <tbody>{WORKFLOW.map(item => { const row = tasks.get(item.task); return <tr key={item.task}><td><b>{item.title}</b><br/><code>{item.task}</code></td><td><span className={`status-tag ${statusClass(row?.status)}`}>{statusText(row?.status)}</span></td><td>{fmt(row?.started_at)}</td><td>{fmt(row?.finished_at)}</td><td>{duration(row)}</td><td>{outputSummary(row)}</td></tr>; })}</tbody></table></div>
    </section>

    <section className="panel" style={{marginBottom: 16}}>
      <div className="panel-heading"><div><h2>手动完整 Agent 链路</h2><p>官方数据 → 外部数据 → Qwen → 模型 → Critic，用于立即触发排查。</p></div><button onClick={runAgents} disabled={running}>{running ? "运行中..." : "运行完整链路"}</button></div>
      <section className="summary-strip" style={{padding: 16, margin: 0}}>
        <span>Provider<b>{agentStatus.data.qwen.provider || "-"}</b></span>
        <span>模型<b>{agentStatus.data.qwen.model || "-"}</b></span>
        <span>最近手动运行<b>{latestManual?.status ?? "尚未运行"}</b></span>
      </section>
      {message && <p style={{padding: "0 16px"}}>{message}</p>}
      {latestManual && <div className="table-scroll"><table className="data-table"><thead><tr><th>Agent</th><th>状态</th><th>开始</th><th>完成</th><th>产出 / 错误</th></tr></thead><tbody>{latestManual.steps.map(step => <tr key={step.id}><td>{step.agent_name}</td><td>{step.status}</td><td>{fmt(step.started_at)}</td><td>{fmt(step.finished_at)}</td><td>{step.error_message || JSON.stringify(step.output).slice(0, 500)}</td></tr>)}</tbody></table></div>}
    </section>

    {loading ? <p className="empty-state">加载中...</p> : error ? <p className="empty-state">{error}</p> : <>
      <div className="two-column"><section className="panel rules-card"><h2>Critic 关键规则</h2><p>没有完整真实输入时直接 NO_BET。</p><p>Qwen 只做有证据的上下文修正，不替代赔率和结果数据。</p><p>最高 EV 未超过动态阈值时禁止推荐。</p><p>模型分歧过高时禁止推荐。</p><p>NO_BET 仓位恒为 0。</p></section><section className="panel"><div className="panel-heading"><div><h2>Critic 输出概览</h2><p>共拦截 {blocked.length} / {matches.length} 场</p></div></div><div className="summary-strip" style={{padding: 16, margin: 0}}><span>通过<b>{matches.length - blocked.length}</b></span><span>拦截<b>{blocked.length}</b></span><span>高风险<b>{matches.filter(match => match.riskLevel === "HIGH").length}</b></span></div></section></div>
      <section className="panel" style={{marginTop: 16}}><div className="panel-heading"><div><h2>逐场 Critic 输入与输出</h2><p>页面 V4 模型的真实规则诊断</p></div></div><div className="table-scroll"><table className="data-table"><thead><tr><th>比赛</th><th>状态</th><th>数据</th><th>最高 EV</th><th>动态阈值</th><th>分歧</th><th>passed</th><th>finalAction</th><th>原因</th></tr></thead><tbody>{matches.map(match => <tr key={match.id}><td>{match.officialMatchId} · {match.homeTeam} vs {match.awayTeam}</td><td>{match.status}</td><td>{match.context?.dataFreshness ?? "STALE"}</td><td>{(Math.max(...Object.values(match.ev)) * 100).toFixed(2)}%</td><td>{Number.isFinite(match.prediction.dynamicEvThreshold) ? `${(match.prediction.dynamicEvThreshold * 100).toFixed(2)}%` : "禁止推荐"}</td><td>{(match.prediction.modelDisagreement.maxDisagreement * 100).toFixed(1)}%</td><td>{String(match.prediction.criticReport.passed)}</td><td>{match.prediction.criticReport.finalAction}</td><td>{match.prediction.criticReport.reasons.join("；") || "通过"}</td></tr>)}</tbody></table></div></section>
    </>}
  </div>;
}
