import AuditLogTable from "./AuditLogTable";
import LiveRecalculationPanel from "./LiveRecalculationPanel";
import OddsMovementChart from "./OddsMovementChart";
import RecommendationStatusBadge from "./RecommendationStatusBadge";
import SnapshotTimeline from "./SnapshotTimeline";
import {listAuditLogs} from "../algorithm/auditLog";
import {getLiveMatchState, initializeLiveMatch} from "../services/liveMonitorService";
import type {OfficialMatch} from "../types";
export default function LiveMatchDetailSection({match}:{match:OfficialMatch}){initializeLiveMatch(match);const state=getLiveMatchState(match.id),status=match.prediction.lifecycleStatus??(match.recommendation==="NO_BET"?"NO_BET":"ACTIVE");return <><section className="panel tabs-panel"><div className="panel-heading"><div><h2>实时快照与推荐状态</h2><p>推荐状态会随官方 SP、外部市场、新闻、首发和比赛状态变化；过期或撤回项目不能继续作为当前依据。</p></div><RecommendationStatusBadge status={status}/></div><OddsMovementChart official={state.officialSnapshots} external={state.externalSnapshots}/><SnapshotTimeline official={state.officialSnapshots} external={state.externalSnapshots}/></section><section className="panel tabs-panel"><h2>实时重算记录</h2><LiveRecalculationPanel rows={state.recalculations}/><AuditLogTable rows={listAuditLogs({entityId:match.id})}/></section></>}
