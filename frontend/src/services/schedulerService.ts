import type {LiveRecalculationTrigger, OfficialMatch, RiskLevel} from "../types";

export const createScheduledTrigger = (match: Pick<OfficialMatch, "id" | "officialMatchId">, description = "Scheduled live refresh", severity: RiskLevel = "LOW"): LiveRecalculationTrigger => ({
  id: `trigger-${match.id}-${Date.now()}`,
  matchId: match.id,
  officialMatchId: match.officialMatchId,
  triggeredAt: new Date().toISOString(),
  type: "SCHEDULED_REFRESH",
  severity,
  description,
});

export const getRefreshIntervalMs = (kickoffTime: string, now = Date.now()) => {
  const minutes = (Date.parse(kickoffTime) - now) / 60_000;
  if (minutes <= 30) return 60_000;
  if (minutes <= 180) return 5 * 60_000;
  return 60 * 60_000;
};
