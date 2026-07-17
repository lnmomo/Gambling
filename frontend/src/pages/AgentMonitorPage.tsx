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
type AllocationReadiness = {
  decision: string;
  strategies: Array<{
    strategy_id: string;
    statistical_evidence?: {
      point_estimates?: {brier_improvement?: number | null; log_loss_improvement?: number | null};
      bootstrap?: {
        settlement_days?: number;
        roi_ci_pct?: {p05?: number | null};
        average_clv_ci?: {p05?: number | null};
      };
    };
  }>;
};
type ExternalConsensusChallenger = {
  decision: string;
  policy: {policy_id: string; registered_at: string};
  decisions: number;
  candidate_decisions: number;
  positive_expected_ev_decisions: number;
  expected_ev_threshold_pass_decisions: number;
  entry_price_eligible_decisions: number;
  entry_price_and_expected_ev_pass_decisions: number;
  positive_conservative_ev_decisions: number;
  best_expected_ev: number | null;
  best_conservative_ev: number | null;
  expected_ev_gap_to_entry: number | null;
  conservative_ev_gap_to_entry: number | null;
  primary_horizon_candidates: number;
  settled_selections: number;
  elapsed_days: number;
  decision_reasons: string[];
  blocker_counts: Array<{reason: string; decisions: number}>;
};

const WORKFLOW: WorkflowItem[] = [
  {task: "official_sp_sync", title: "官方赛事/SP", description: "中国竞彩网赛事池、状态、官方赔率"},
  {task: "official_results_sync", title: "官方赛果回填", description: "独立赛果页、90分钟比分、冲突隔离与不可变证据", dependsOn: "official_sp_sync"},
  {task: "paper_portfolio_settlement", title: "纸面组合结算", description: "用官方赛果和临场SP结算不可变持仓、收益与CLV", dependsOn: "official_results_sync"},
  {task: "official_sp_evidence_quality", title: "SP 证据质量", description: "采集新鲜度、临盘覆盖、赛果完整性与时间一致性", dependsOn: "paper_portfolio_settlement"},
  {task: "prospective_research_critical_capture", title: "关键窗口冻结", description: "每15分钟冻结最新可得SP和模型输入，覆盖T-120至T-60主窗口", dependsOn: "official_sp_evidence_quality"},
  {task: "external_odds_news_weather_sync", title: "外部赔率/新闻/天气", description: "The Odds API、新闻、天气与场地元数据", dependsOn: "official_sp_sync"},
  {task: "historical_data_sync", title: "历史库扩充", description: "联赛、全球、国家队历史 CSV 增量归档", dependsOn: "external_odds_news_weather_sync"},
  {task: "feature_build", title: "球队特征", description: "历史样本、Elo、lambda、source confidence", dependsOn: "historical_data_sync"},
  {task: "prospective_research_capture", title: "完整前瞻研究归档", description: "小时级特征刷新后冻结模型、赛前赔率与不可覆盖赛前预测", dependsOn: "feature_build"},
  {task: "external_consensus_challenger_capture", title: "外部共识 Challenger", description: "冻结多家公司去水共识、官方SP、保守EV与真实NO_BET，禁止赛后改规则", dependsOn: "prospective_research_capture"},
  {task: "qwen_news_analysis", title: "Qwen 情报", description: "新闻摘要、伤停与上下文因子", dependsOn: "external_odds_news_weather_sync"},
  {task: "market_bias_shadow_monitor", title: "市场偏差影子验证", description: "冻结规则、影子预测、赛后评估与晋级门", dependsOn: "feature_build"},
  {task: "profit_scorer_official_pool_diagnosis", title: "盈利评分池诊断", description: "检查当前官方比赛是否进入冻结盈利评分器", dependsOn: "feature_build"},
  {task: "profit_scorer_official_sp_validation", title: "官方 SP 前瞻验证", description: "冻结赛前决策；按结算日 Bootstrap ROI/CLV，并与去水市场校准对比", dependsOn: "profit_scorer_official_pool_diagnosis"},
  {task: "profit_allocation_readiness", title: "每日资金质量门", description: "样本、月份、ROI/CLV 置信下界、相对市场校准与回撤全部通过后才分配预算", dependsOn: "profit_scorer_official_sp_validation"},
  {task: "paper_portfolio_allocation", title: "纸面组合建仓", description: "按最新可执行SP、四分之一Kelly、方向/联赛/长赔集中度上限写入不可变账本；动态回撤规则先影子验证", dependsOn: "profit_allocation_readiness"},
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
  const allocationReadiness = useApi<AllocationReadiness>("/api/profit/allocation-readiness", {decision: "NOT_RUN", strategies: []});
  const consensusChallenger = useApi<ExternalConsensusChallenger>(
    "/api/research/external-consensus-challenger",
    {decision: "NOT_RUN", policy: {policy_id: "-", registered_at: ""}, decisions: 0, candidate_decisions: 0,
      positive_expected_ev_decisions: 0, expected_ev_threshold_pass_decisions: 0,
      entry_price_eligible_decisions: 0, entry_price_and_expected_ev_pass_decisions: 0,
      positive_conservative_ev_decisions: 0, best_expected_ev: null, best_conservative_ev: null,
      expected_ev_gap_to_entry: null, conservative_ev_gap_to_entry: null,
      primary_horizon_candidates: 0, settled_selections: 0, elapsed_days: 0, decision_reasons: [], blocker_counts: []},
  );
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
  const evidence = health?.officialSpEvidenceQuality;
  const scorerEvidence = health?.profitScorerOfficialSp;
  const scorerStrategy = allocationReadiness.data.strategies.find(
    strategy => strategy.statistical_evidence?.bootstrap,
  ) ?? allocationReadiness.data.strategies[0];
  const scorerStatistics = scorerStrategy?.statistical_evidence;
  const scorerBootstrap = scorerStatistics?.bootstrap;
  const scorerPoint = scorerStatistics?.point_estimates;
  const pct = (value?: number | null) => value == null ? "-" : `${value.toFixed(2)}%`;
  const decimal = (value?: number | null) => value == null ? "-" : value.toFixed(4);

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
        <div><h2>自动化服务工作链路</h2><p>服务启动后立即执行；官方 SP、赛果、证据检查和关键窗口冻结每 15 分钟执行，其余重任务每小时执行，每一步都写入 task_runs。</p></div>
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
      <div className="panel-heading"><div><h2>官方 SP 证据质量门</h2><p>只有采集新鲜、临盘与赛果覆盖完整的数据才能用于 CLV、收益和资金晋级。</p></div></div>
      <section className="summary-strip" style={{padding: 16, margin: 0}}>
        <span>结论<b>{evidence?.decision ?? "NOT_RUN"}</b></span>
        <span>观测数<b>{evidence?.summary.observations ?? 0}</b></span>
        <span>赛前赛事卡观测<b>{evidence?.summary.availability_observations ?? 0}</b></span>
        <span>已开售比赛<b>{evidence?.summary.offered_matches ?? 0}</b></span>
        <span>赛前比赛<b>{evidence?.summary.pre_match_matches ?? 0}</b></span>
        <span>已开赛临盘样本<b>{evidence?.summary.closing_eligible_matches ?? 0}</b></span>
        <span>采集延迟<b>{evidence?.summary.freshness_hours == null ? "-" : `${evidence.summary.freshness_hours.toFixed(1)} 小时`}</b></span>
        <span>赛前 SP 覆盖<b>{((evidence?.summary.pre_match_sp_coverage ?? 0) * 100).toFixed(1)}%</b></span>
        <span>1 小时临盘覆盖<b>{((evidence?.summary.closing_1h_coverage ?? 0) * 100).toFixed(1)}%</b></span>
        <span>赛果覆盖<b>{((evidence?.summary.settlement_coverage ?? 0) * 100).toFixed(1)}%</b></span>
      </section>
      <div className="table-scroll"><table className="data-table"><thead><tr><th>检查</th><th>结果</th><th>证据</th><th>影响</th><th>修复动作</th></tr></thead>
        <tbody>{(evidence?.checks ?? []).map(check => <tr key={check.id}><td><code>{check.id}</code></td><td><span className={`status-tag ${check.status === "PASS" ? "running" : check.status === "PENDING" ? "delayed" : "alert"}`}>{check.status}</span></td><td>{check.evidence}</td><td>{check.impact}</td><td>{check.remediation}</td></tr>)}</tbody></table></div>
    </section>

    <section className="panel" style={{marginBottom: 16}}>
      <div className="panel-heading"><div><h2>冻结盈利评分决策账本</h2><p>每个开盘快照与 scorer 版本只能冻结一次；阻塞或错过赛前窗口后禁止追溯重算。</p></div></div>
      <section className="summary-strip" style={{padding: 16, margin: 0}}>
        <span>任务状态<b>{scorerEvidence?.status ?? "NOT_RUN"}</b></span>
        <span>统计策略<b>{scorerStrategy?.strategy_id ?? "-"}</b></span>
        <span>冻结尝试<b>{scorerEvidence?.frozenAttempts ?? 0}</b></span>
        <span>成功评分<b>{scorerEvidence?.frozenScoredAttempts ?? 0}</b></span>
        <span>赛前阻塞<b>{scorerEvidence?.frozenBlockedAttempts ?? 0}</b></span>
        <span>错过赛前<b>{scorerEvidence?.missedPreMatchAttempts ?? 0}</b></span>
        <span>时间违规<b>{scorerEvidence?.frozenEvidenceTemporalViolations ?? 0}</b></span>
        <span>通过评分器<b>{scorerEvidence?.selectedSnapshots ?? 0}</b></span>
        <span>已结算选择<b>{scorerEvidence?.settledSelectedSnapshots ?? 0}</b></span>
        <span>剩余结算样本<b>{scorerEvidence?.remainingSettledSelected ?? 200}</b></span>
        <span>结算日组数<b>{scorerBootstrap?.settlement_days ?? 0}</b></span>
        <span>ROI 95% 下界<b>{pct(scorerBootstrap?.roi_ci_pct?.p05)}</b></span>
        <span>CLV 95% 下界<b>{decimal(scorerBootstrap?.average_clv_ci?.p05)}</b></span>
        <span>Brier 相对市场改善<b>{decimal(scorerPoint?.brier_improvement)}</b></span>
        <span>Log Loss 相对市场改善<b>{decimal(scorerPoint?.log_loss_improvement)}</b></span>
        <span>准入结论<b>{scorerEvidence?.decision ?? "等待证据"}</b></span>
      </section>
      {(scorerEvidence?.decisionReasons?.length ?? 0) > 0 && <p style={{padding: "0 16px", color: "var(--muted)"}}>阻塞原因：{scorerEvidence?.decisionReasons.join("；")}</p>}
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
      <div className="panel-heading"><div><h2>外部市场共识 Challenger</h2><p>用同一赛前时刻的多家公司去水概率评估官方 SP；政策和每次 CANDIDATE / NO_BET 均不可变。</p></div></div>
      <section className="summary-strip" style={{padding: 16, margin: 0}}>
        <span>状态<b>{consensusChallenger.data.decision}</b></span>
        <span>冻结决策<b>{consensusChallenger.data.decisions}</b></span>
        <span>候选决策<b>{consensusChallenger.data.candidate_decisions}</b></span>
        <span>点估计正 EV<b>{consensusChallenger.data.positive_expected_ev_decisions}</b></span>
        <span>价格范围合格<b>{consensusChallenger.data.entry_price_eligible_decisions}</b></span>
        <span>价格与点估计均通过<b>{consensusChallenger.data.entry_price_and_expected_ev_pass_decisions}</b></span>
        <span>保守 EV 非负<b>{consensusChallenger.data.positive_conservative_ev_decisions}</b></span>
        <span>最佳点估计 EV<b>{pct(consensusChallenger.data.best_expected_ev == null ? null : consensusChallenger.data.best_expected_ev * 100)}</b></span>
        <span>最佳保守 EV<b>{pct(consensusChallenger.data.best_conservative_ev == null ? null : consensusChallenger.data.best_conservative_ev * 100)}</b></span>
        <span>距点估计门槛<b>{pct(consensusChallenger.data.expected_ev_gap_to_entry == null ? null : consensusChallenger.data.expected_ev_gap_to_entry * 100)}</b></span>
        <span>距保守 EV 门槛<b>{pct(consensusChallenger.data.conservative_ev_gap_to_entry == null ? null : consensusChallenger.data.conservative_ev_gap_to_entry * 100)}</b></span>
        <span>主窗口候选<b>{consensusChallenger.data.primary_horizon_candidates}</b></span>
        <span>已结算选择<b>{consensusChallenger.data.settled_selections}</b></span>
        <span>注册天数<b>{consensusChallenger.data.elapsed_days} / 180</b></span>
      </section>
      <p style={{padding: "0 16px", color: "var(--muted)"}}>
        当前主要阻断：{consensusChallenger.data.blocker_counts.slice(0, 4).map(item => `${item.reason} (${item.decisions})`).join("；") || "等待首次采集"}
      </p>
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
