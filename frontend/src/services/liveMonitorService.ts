import type {ExternalOddsSnapshot, LiveRecalculationResult, LiveRecalculationTrigger, MarketMovementSignal, OfficialMatch, OfficialSpSnapshot} from "../types";
import {appendAuditLog} from "../algorithm/auditLog";
import {buildLiveRecalculationResult} from "../algorithm/liveRecalculation";
import {detectExternalMarketMovement, detectOfficialExternalDivergence, detectOfficialSpMovement} from "../algorithm/oddsMovement";
import {getLatestExternalOddsSnapshot, listExternalOddsSnapshots, saveExternalOddsSnapshot} from "./externalOddsSnapshotService";
import {getLatestOfficialSpSnapshot, listOfficialSpSnapshots, saveOfficialSpSnapshot} from "./officialSpSnapshotService";

export interface LiveMatchState { officialSnapshots: OfficialSpSnapshot[]; externalSnapshots: ExternalOddsSnapshot[]; signals: MarketMovementSignal[]; recalculations: LiveRecalculationResult[] }
const recalculationStore = new Map<string, LiveRecalculationResult[]>();

export function captureLiveSnapshots(match: OfficialMatch, capturedAt = new Date().toISOString()) {
  const previousOfficial = getLatestOfficialSpSnapshot(match.id), previousExternal = getLatestExternalOddsSnapshot(match.id);
  const official = saveOfficialSpSnapshot(match, capturedAt), external = saveExternalOddsSnapshot(match, capturedAt);
  const signals = [
    ...(previousOfficial ? detectOfficialSpMovement(previousOfficial, official) : []),
    ...(previousExternal ? detectExternalMarketMovement(previousExternal, external) : []),
    ...detectOfficialExternalDivergence(official, external),
  ];
  appendAuditLog({entityType: "ODDS_SNAPSHOT", entityId: match.id, action: "SNAPSHOT_CREATED", summary: `Captured ${official.snapshotType} official and external market snapshots.`, after: {official, external}, severity: signals.some(signal => signal.severity === "HIGH") ? "WARNING" : "INFO", actor: "SCHEDULER"});
  return {official, external, signals};
}

export function runLiveRecalculation(match: OfficialMatch, trigger: LiveRecalculationTrigger): LiveRecalculationResult {
  const rows = recalculationStore.get(match.id) ?? [], previous = rows.length ? rows[rows.length - 1].newPrediction : match.prediction;
  const result = buildLiveRecalculationResult(match, trigger, {...match.prediction, recalculationId: trigger.id}, previous);
  rows.push(result); recalculationStore.set(match.id, rows);
  appendAuditLog({entityType: "PREDICTION", entityId: match.id, action: "PREDICTION_RECALCULATED", summary: `Prediction recalculated: ${result.lifecycleStatus}.`, before: previous, after: result.newPrediction, trigger, severity: result.lifecycleStatus === "ACTIVE" ? "INFO" : "WARNING", actor: trigger.type === "MANUAL_REFRESH" ? "USER" : "SCHEDULER"});
  return result;
}

export function initializeLiveMatch(match: OfficialMatch) {
  if (!getLatestOfficialSpSnapshot(match.id)) captureLiveSnapshots(match);
  return getLiveMatchState(match.id);
}

export function getLiveMatchState(matchId: string): LiveMatchState {
  const officialSnapshots = listOfficialSpSnapshots(matchId), externalSnapshots = listExternalOddsSnapshots(matchId);
  const latestOfficial = officialSnapshots[officialSnapshots.length - 1], latestExternal = externalSnapshots[externalSnapshots.length - 1];
  return {officialSnapshots, externalSnapshots, signals: latestOfficial && latestExternal ? detectOfficialExternalDivergence(latestOfficial, latestExternal) : [], recalculations: [...(recalculationStore.get(matchId) ?? [])]};
}
