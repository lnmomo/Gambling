import {useMemo, useState} from "react";
import AuditLogTable from "../components/AuditLogTable";
import LiveRecalculationPanel from "../components/LiveRecalculationPanel";
import MarketMovementAlertPanel from "../components/MarketMovementAlertPanel";
import OddsMovementChart from "../components/OddsMovementChart";
import PageHeader from "../components/PageHeader";
import SnapshotTimeline from "../components/SnapshotTimeline";
import {listAuditLogs} from "../algorithm/auditLog";
import useOfficialMatches from "../hooks/useOfficialMatches";
import {captureLiveSnapshots, getLiveMatchState, initializeLiveMatch, runLiveRecalculation} from "../services/liveMonitorService";
import type {OfficialMatch} from "../types";

export default function LiveMonitorPage() {
  const {matches, loading, error} = useOfficialMatches(), [selectedId, setSelectedId] = useState(""), [revision, setRevision] = useState(0);
  const selected = matches.find(match => match.id === selectedId) ?? matches[0];
  const state = useMemo(() => selected ? initializeLiveMatch(selected) : undefined, [selected, revision]);
  const refresh = (match: OfficialMatch) => { const captured = captureLiveSnapshots(match); runLiveRecalculation(match, {id: `manual-${Date.now()}`, matchId: match.id, officialMatchId: match.officialMatchId, triggeredAt: new Date().toISOString(), type: "MANUAL_REFRESH", severity: captured.signals.some(signal => signal.severity === "HIGH") ? "HIGH" : "LOW", description: "Manual live market refresh", previousSnapshotId: state?.officialSnapshots[state.officialSnapshots.length - 1]?.id, newSnapshotId: captured.official.id}); setRevision(value => value + 1); };
  return <div className="page"><PageHeader title="实时监控与模型治理" subtitle="跟踪官方 SP、外部市场、推荐生命周期、重算记录和审计证据。"/><section className="panel"><div className="panel-heading"><div><h2>监控比赛</h2><p>临场 30 分钟内建议按分钟刷新；更早比赛按分层周期刷新。</p></div>{selected && <button onClick={() => refresh(selected)}>立即抓取并重算</button>}</div>{loading ? <p>加载中...</p> : error ? <p>{error}</p> : <select value={selected?.id ?? ""} onChange={event => setSelectedId(event.target.value)}>{matches.map(match => <option key={match.id} value={match.id}>{match.officialMatchId} · {match.homeTeam} vs {match.awayTeam}</option>)}</select>}</section>{selected && state && <><section className="panel"><h2>赔率变化</h2><OddsMovementChart official={state.officialSnapshots} external={state.externalSnapshots}/><MarketMovementAlertPanel signals={state.signals}/></section><div className="two-column"><section className="panel"><h2>快照时间线</h2><SnapshotTimeline official={state.officialSnapshots} external={state.externalSnapshots}/></section><section className="panel"><h2>实时重算</h2><LiveRecalculationPanel rows={state.recalculations}/></section></div><section className="panel"><h2>审计日志</h2><AuditLogTable rows={listAuditLogs({entityId: selected.id})}/></section></>}</div>;
}
