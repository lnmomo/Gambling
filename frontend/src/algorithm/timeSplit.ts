import type {HistoricalMatch} from "../types";
export const getPastMatchesOnly = (matches: HistoricalMatch[], cutoffTime: string) => {
  const cutoff = new Date(cutoffTime).getTime();
  return matches.filter(match => new Date(match.playedAt).getTime() < cutoff);
};
export function splitHistoricalDataByTime(matches: HistoricalMatch[], options?: {trainEndDate: string; validationEndDate: string; testEndDate: string}) {
  const sorted = [...matches].sort((a, b) => new Date(a.playedAt).getTime() - new Date(b.playedAt).getTime());
  if (options) return {train: sorted.filter(x => x.playedAt <= options.trainEndDate), validation: sorted.filter(x => x.playedAt > options.trainEndDate && x.playedAt <= options.validationEndDate), test: sorted.filter(x => x.playedAt > options.validationEndDate && x.playedAt <= options.testEndDate)};
  const trainEnd = Math.floor(sorted.length * .70), validationEnd = Math.floor(sorted.length * .85);
  return {train: sorted.slice(0, trainEnd), validation: sorted.slice(trainEnd, validationEnd), test: sorted.slice(validationEnd)};
}
