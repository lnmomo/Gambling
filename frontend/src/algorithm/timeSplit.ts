import type {HistoricalMatch} from "../types";
export const sortMatchesByTime = <T extends {kickoffTime?: string; playedAt?: string}>(matches: T[]) => [...matches].sort((a, b) => new Date(a.playedAt ?? a.kickoffTime ?? "").getTime() - new Date(b.playedAt ?? b.kickoffTime ?? "").getTime());
export const getPastMatchesOnly = (matches: HistoricalMatch[], cutoffTime: string) => {
  const cutoff = new Date(cutoffTime).getTime();
  if (!Number.isFinite(cutoff)) return [];
  return sortMatchesByTime(matches.filter(match => { const playedAt = new Date(match.playedAt).getTime(); return Number.isFinite(playedAt) && playedAt < cutoff; }));
};
export function assertNoFutureLeakage(pastMatches: HistoricalMatch[], cutoffTime: string) {
  const cutoff = new Date(cutoffTime).getTime();
  const invalid = pastMatches.filter(match => { const time = new Date(match.playedAt).getTime(); return !Number.isFinite(time) || time >= cutoff; });
  return {valid: invalid.length === 0, leakageCount: invalid.length, warnings: invalid.map(match => `历史比赛 ${match.id} 不早于回测截止时间，已排除。`)};
}
export function splitMatchesByTime<T extends {kickoffTime?: string; playedAt?: string}>(matches: T[], options: {trainRatio?: number; validationRatio?: number; testRatio?: number} = {}) {
  const sorted = sortMatchesByTime(matches), trainRatio = options.trainRatio ?? .70, validationRatio = options.validationRatio ?? .15, testRatio = options.testRatio ?? .15;
  if (Math.abs(trainRatio + validationRatio + testRatio - 1) > 1e-9) throw new Error("时间切分比例之和必须为 1。");
  const trainEnd = Math.floor(sorted.length * trainRatio), validationEnd = trainEnd + Math.floor(sorted.length * validationRatio);
  return {train: sorted.slice(0, trainEnd), validation: sorted.slice(trainEnd, validationEnd), test: sorted.slice(validationEnd)};
}
export const splitHistoricalDataByTime = splitMatchesByTime;
