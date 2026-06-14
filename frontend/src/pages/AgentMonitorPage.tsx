import {useState} from "react";
import PageHeader from "../components/PageHeader";
import useApi from "../hooks/useApi";
import useOfficialMatches from "../hooks/useOfficialMatches";

type AgentStep = {id: number; agent_name: string; status: string; error_message: string | null; started_at: string; finished_at: string | null; output: Record<string, unknown>};
type AgentRun = {id: string; status: string; trigger_name: string; started_at: string; finished_at: string | null; summary: Record<string, unknown>; steps: AgentStep[]};
type AgentStatus = {qwen: {configured: boolean; provider: string; model: string; base_host: string}; runs: AgentRun[]};

export default function AgentMonitorPage() {
  const {matches, loading, error} = useOfficialMatches();
  const status = useApi<AgentStatus>("/api/agents/status", {qwen: {configured: false, provider: "", model: "", base_host: ""}, runs: []});
  const [running, setRunning] = useState(false), [message, setMessage] = useState("");
  const blocked = matches.filter(match => !match.prediction.criticReport.passed), latest = status.data.runs[0];
  const runAgents = async () => {
    setRunning(true); setMessage("正在运行官方数据、外部数据、Qwen、模型与 Critic...");
    try {
      const response = await fetch("/api/agents/run", {method: "POST"});
      if (!response.ok) throw new Error(await response.text());
      const run = await response.json() as AgentRun;
      setMessage(`运行完成：${run.status}，共 ${run.steps.length} 个步骤`); status.reload();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Agent 运行失败"); }
    finally { setRunning(false); }
  };
  return <div className="page">
    <PageHeader title="Agent / Workflow 监控" subtitle="展示真实接口调用、Qwen 分析、模型计算与 Critic 的持久化运行记录" />
    <section className="panel" style={{marginBottom: 16}}>
      <div className="panel-heading"><div><h2>完整 Agent 链路</h2><p>官方赛程 → 赔率 / 新闻 / 天气 → Qwen 情报 → 概率模型 → Critic</p></div><button onClick={runAgents} disabled={running}>{running ? "运行中..." : "运行完整 Agent 链路"}</button></div>
      <div className="summary-strip" style={{padding: 16, margin: 0}}>
        <span>Qwen 配置<b>{status.data.qwen.configured ? "已连接" : "未配置"}</b></span>
        <span>Provider<b>{status.data.qwen.provider || "-"}</b></span><span>模型<b>{status.data.qwen.model || "-"}</b></span>
        <span>最近运行<b>{latest?.status ?? "尚未运行"}</b></span>
      </div>
      {message && <p style={{padding: "0 16px"}}>{message}</p>}
      {latest && <div className="table-scroll"><table className="data-table"><thead><tr><th>Agent</th><th>状态</th><th>开始</th><th>完成</th><th>产出 / 错误</th></tr></thead><tbody>{latest.steps.map(step => <tr key={step.id}><td>{step.agent_name}</td><td>{step.status}</td><td>{new Date(step.started_at).toLocaleString("zh-CN")}</td><td>{step.finished_at ? new Date(step.finished_at).toLocaleString("zh-CN") : "-"}</td><td>{step.error_message || JSON.stringify(step.output)}</td></tr>)}</tbody></table></div>}
    </section>
    {loading ? <p className="empty-state">加载中...</p> : error ? <p className="empty-state">{error}</p> : <>
      <div className="two-column"><section className="panel rules-card"><h2>Critic 关键规则</h2><p>无完整真实输入时直接 NO_BET。</p><p>Qwen 只能做有证据的小幅上下文修正。</p><p>最高 EV 未超过动态阈值时禁止推荐。</p><p>模型分歧过高时禁止推荐。</p><p>NO_BET 仓位恒为 0。</p></section><section className="panel"><div className="panel-heading"><div><h2>Critic 输出概览</h2><p>共拦截 {blocked.length} / {matches.length} 场</p></div></div><div className="summary-strip" style={{padding: 16, margin: 0}}><span>通过<b>{matches.length - blocked.length}</b></span><span>拦截<b>{blocked.length}</b></span><span>高风险<b>{matches.filter(match => match.riskLevel === "HIGH").length}</b></span></div></section></div>
      <section className="panel" style={{marginTop: 16}}><div className="panel-heading"><div><h2>逐场 Critic 输入与输出</h2><p>页面 V4 模型的真实规则诊断</p></div></div><div className="table-scroll"><table className="data-table"><thead><tr><th>比赛</th><th>状态</th><th>数据</th><th>最高 EV</th><th>动态阈值</th><th>分歧</th><th>passed</th><th>finalAction</th><th>原因</th></tr></thead><tbody>{matches.map(match => <tr key={match.id}><td>{match.officialMatchId} · {match.homeTeam} vs {match.awayTeam}</td><td>{match.status}</td><td>{match.context?.dataFreshness ?? "STALE"}</td><td>{(Math.max(...Object.values(match.ev)) * 100).toFixed(2)}%</td><td>{(match.prediction.dynamicEvThreshold * 100).toFixed(2)}%</td><td>{(match.prediction.modelDisagreement.maxDisagreement * 100).toFixed(1)}%</td><td>{String(match.prediction.criticReport.passed)}</td><td>{match.prediction.criticReport.finalAction}</td><td>{match.prediction.criticReport.reasons.join("；") || "通过"}</td></tr>)}</tbody></table></div></section>
    </>}
  </div>;
}
