import {Link} from "react-router-dom";
import type {SystemHealth} from "../services/healthService";
import {formatHealthTime, summarizeSystemHealth} from "../services/systemStatusService";

export default function SystemHealthPanel({health, compact=false}:{health:SystemHealth; compact?:boolean}) {
  const summary = summarizeSystemHealth(health);
  return <section className="panel">
    <div className="panel-heading"><div><h2>System Health</h2><p>健康检查只表示数据和任务状态，不代表推荐一定准确。</p></div>{compact&&<Link to="/system-health">查看详情</Link>}</div>
    <section className="summary-strip" style={{padding:16,margin:0}}>
      <span>系统状态<b>{summary.statusLabel}</b></span>
      <span>数据库<b>{summary.databaseLabel}</b></span>
      <span>官方 SP<b>{health.officialSpSync.status}</b></span>
      <span>外部赔率<b>{health.externalOddsSync.status}</b></span>
      <span>今日任务<b>{summary.taskSummary}</b></span>
      <span>最近错误<b>{health.recentErrors}</b></span>
      <span>API Key<b>{summary.apiKeyLabel}</b></span>
      <span>自动下注<b>{summary.autoBettingLabel}</b></span>
    </section>
    {!compact&&<div className="summary-strip" style={{padding:16,marginTop:12}}>
      <span>官方最后成功<b>{formatHealthTime(health.officialSpSync.lastSuccessAt)}</b></span>
      <span>外部最后成功<b>{formatHealthTime(health.externalOddsSync.lastSuccessAt)}</b></span>
      <span>Champion<b>{health.model.championVersion ?? "-"}</b></span>
      <span>Stacking<b>{health.model.stackingEnabled ? "Enabled" : "Disabled"}</b></span>
    </div>}
    {health.warnings.length>0&&<div className="notice warning"><b>Warnings</b><ul>{health.warnings.map(item=><li key={item}>{item}</li>)}</ul></div>}
  </section>;
}
