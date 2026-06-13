import type {HistoricalMatch, LeagueParameters} from "../types";
import {AlgorithmConfig} from "./config";
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
function fromMatches(matches: HistoricalMatch[], league: string): LeagueParameters {
  const count = matches.length || 1, homeGoals = matches.reduce((s, m) => s + m.homeGoals, 0), awayGoals = matches.reduce((s, m) => s + m.awayGoals, 0);
  const homeWins = matches.filter(m => m.homeGoals > m.awayGoals).length, draws = matches.filter(m => m.homeGoals === m.awayGoals).length;
  const avgHomeGoals = homeGoals / count || 1.45, avgAwayGoals = awayGoals / count || 1.15, drawRate = draws / count;
  return {league, matchCount: matches.length, avgHomeGoals, avgAwayGoals, avgTotalGoals: avgHomeGoals + avgAwayGoals, homeWinRate: homeWins / count, drawRate, awayWinRate: (matches.length - homeWins - draws) / count, baseDrawRate: drawRate, homeAdvantageFactor: clamp(avgHomeGoals / Math.max(.1, avgAwayGoals), .95, 1.20), defaultRho: clamp(drawRate > .30 ? -.13 : drawRate < .22 ? -.06 : AlgorithmConfig.dixonColes.defaultRho, AlgorithmConfig.dixonColes.minRho, AlgorithmConfig.dixonColes.maxRho), reliability: matches.length >= 300 ? "HIGH" : matches.length >= 100 ? "MEDIUM" : "LOW"};
}
export function estimateLeagueParameters(matches: HistoricalMatch[], league: string): LeagueParameters {
  const leagueMatches = matches.filter(match => match.league === league);
  return leagueMatches.length >= 50 ? fromMatches(leagueMatches, league) : {...fromMatches(matches, "GLOBAL"), league, matchCount: leagueMatches.length, reliability: "LOW"};
}
export const estimateAllLeagueParameters = (matches: HistoricalMatch[]) => Object.fromEntries([...new Set(matches.map(match => match.league))].map(league => [league, estimateLeagueParameters(matches, league)]));
export const getLeagueParameters = (league: string, all: Record<string, LeagueParameters>, matches: HistoricalMatch[] = []) => all[league] ?? estimateLeagueParameters(matches, league);
