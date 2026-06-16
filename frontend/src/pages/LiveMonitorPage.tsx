import {useEffect, useMemo, useState} from "react";
import {Link} from "react-router-dom";
import AuditLogTable from "../components/AuditLogTable";
import LiveRecalculationPanel from "../components/LiveRecalculationPanel";
import MarketMovementAlertPanel from "../components/MarketMovementAlertPanel";
import OddsMovementChart from "../components/OddsMovementChart";
import PageHeader from "../components/PageHeader";
import RecommendationStatusBadge from "../components/RecommendationStatusBadge";
import SnapshotTimeline from "../components/SnapshotTimeline";
import {listAuditLogs} from "../algorithm/auditLog";
import useOfficialMatches from "../hooks/useOfficialMatches";
import {fetchSystemHealth, type SystemHealth} from "../services/healthService";
import {captureLiveSnapshots, getLiveMatchState, initializeLiveMatch, runLiveRecalculation} from "../services/liveMonitorService";
import type {OfficialMatch, RecommendationLifecycleStatus} from "../types";
const statusOf=(match:OfficialMatch):RecommendationLifecycleStatus=>match.prediction.lifecycleStatus??(match.recommendation==="NO_BET"?"NO_BET":"ACTIVE");
const pct=(value:number)=>Number.isFinite(value)?`${(value*100).toFixed(1)}%`:"-";
export default function LiveMonitorPage(){
  const {matches,loading,error}=useOfficialMatches(),[selectedId,setSelectedId]=useState(""),[revision,setRevision]=useState(0);
  const [health,setHealth]=useState<SystemHealth|null>(null);
  useEffect(()=>{let alive=true;fetchSystemHealth().then(data=>{if(alive)setHealth(data)});return()=>{alive=false}},[]);
  const states=useMemo(()=>new Map(matches.map(match=>[match.id,initializeLiveMatch(match)])),[matches,revision]);
  const selected=matches.find(match=>match.id===selectedId)??matches[0],state=selected?states.get(selected.id):undefined;
  const active=matches.filter(match=>statusOf(match)==="ACTIVE").length,stale=matches.filter(match=>statusOf(match)==="STALE").length,withdrawn=matches.filter(match=>statusOf(match)==="WITHDRAWN").length;
  const highMoves=[...states.values()].reduce((sum,row)=>sum+row.signals.filter(signal=>signal.severity==="HIGH").length,0),recalculations=[...states.values()].reduce((sum,row)=>sum+row.recalculations.length,0);
  const refresh=(match:OfficialMatch)=>{const before=getLiveMatchState(match.id),captured=captureLiveSnapshots(match),trigger={id:`manual-${Date.now()}`,matchId:match.id,officialMatchId:match.officialMatchId,triggeredAt:new Date().toISOString(),type:"MANUAL_REFRESH" as const,severity:captured.signals.some(signal=>signal.severity==="HIGH")?"HIGH" as const:"LOW" as const,description:"Manual live market refresh",previousSnapshotId:before.officialSnapshots[before.officialSnapshots.length-1]?.id,newSnapshotId:captured.official.id};runLiveRecalculation(match,trigger);setRevision(value=>value+1)};
  return <div className="page"><PageHeader title="实时监控与模型治理" subtitle="跟踪官方 SP、外部市场、推荐生命周期、重算记录和审计证据。"/>
    {health&&health.status!=="healthy"&&<section className="panel"><div className="notice warning"><b>数据质量与任务状态提示</b><p>官方 SP：{health.officialSpSync.status}；外部赔率：{health.externalOddsSync.status}；最近错误：{health.recentErrors}。任务失败时系统不应继续创建假推荐。</p>{health.warnings.length>0&&<ul>{health.warnings.map(item=><li key={item}>{item}</li>)}</ul>}</div></section>}
    <section className="summary-strip"><span>官方比赛<b>{matches.length}</b></span><span>官方 SP 快照覆盖<b>{[...states.values()].filter(row=>row.officialSnapshots.length).length}</b></span><span>外部市场覆盖<b>{[...states.values()].filter(row=>row.externalSnapshots.some(snapshot=>snapshot.isValid)).length}</b></span><span>ACTIVE / STALE<b>{active} / {stale}</b></span><span>WITHDRAWN<b>{withdrawn}</b></span><span>HIGH 异动<b>{highMoves}</b></span><span>今日重算<b>{recalculations}</b></span></section>
    <section className="panel"><div className="panel-heading"><div><h2>实时比赛表</h2><p>停赛、结束或已开赛项目不会继续生成 ACTIVE 推荐。</p></div></div>{loading?<p>加载中...</p>:error?<p>{error}</p>:<div className="table-scroll"><table className="data-table"><thead><tr><th>开赛时间</th><th>比赛</th><th>官方更新</th><th>外部更新</th><th>最终概率</th><th>EV</th><th>生命周期</th><th>重算</th><th>操作</th></tr></thead><tbody>{matches.map(match=>{const row=states.get(match.id);return <tr key={match.id}><td>{new Date(match.kickoffTime).toLocaleString("zh-CN")}</td><td>{match.league}<br/><b>{match.homeTeam} vs {match.awayTeam}</b></td><td>{row?.officialSnapshots.length?new Date(row.officialSnapshots[row.officialSnapshots.length-1].capturedAt).toLocaleTimeString("zh-CN"):"-"}</td><td>{row?.externalSnapshots.length?new Date(row.externalSnapshots[row.externalSnapshots.length-1].capturedAt).toLocaleTimeString("zh-CN"):"-"}</td><td>{Object.values(match.prediction.finalProbability).map(pct).join(" / ")}</td><td>{Object.values(match.prediction.ev).map(pct).join(" / ")}</td><td><RecommendationStatusBadge status={statusOf(match)}/></td><td>{row?.recalculations.length??0}</td><td><button onClick={()=>{setSelectedId(match.id);refresh(match)}}>手动重算</button> <Link to={`/matches/${match.id}`}>详情</Link></td></tr>})}</tbody></table></div>}</section>
    {selected&&state&&<><section className="panel"><div className="panel-heading"><div><h2>{selected.homeTeam} vs {selected.awayTeam}</h2><p>官方与外部市场概率变化</p></div><button onClick={()=>refresh(selected)}>立即抓取并重算</button></div><OddsMovementChart official={state.officialSnapshots} external={state.externalSnapshots}/><MarketMovementAlertPanel signals={state.signals}/></section><div className="two-column"><section className="panel"><h2>快照时间线</h2><SnapshotTimeline official={state.officialSnapshots} external={state.externalSnapshots}/></section><section className="panel"><h2>实时重算</h2><LiveRecalculationPanel rows={state.recalculations}/></section></div><section className="panel"><h2>审计日志</h2><AuditLogTable rows={listAuditLogs({entityId:selected.id})}/></section></>}
  </div>;
}
