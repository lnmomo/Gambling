import type {HistoricalMatch} from "../types";
import {AlgorithmConfig} from "./config";
import {normalizeTeamName} from "./teamNameNormalizer";
export const calculateTimeDecayWeight = (daysAgo: number, halfLife = AlgorithmConfig.poisson.halfLife) => Math.exp(-Math.max(0, daysAgo) / Math.max(1, halfLife));
export function getDaysAgo(date: string, now = new Date()): number { const time = new Date(date).getTime(); return Number.isFinite(time) ? Math.max(0, (now.getTime() - time) / 86_400_000) : 0; }
export function buildWeightedTeamStats(matches: HistoricalMatch[], teamName: string, options: {league?: string; cutoffTime?: string; halfLife?: number; minMatches?: number} | string = {}) {
  const config = typeof options === "string" ? {league: options} : options, team = normalizeTeamName(teamName), cutoff = config.cutoffTime ? new Date(config.cutoffTime).getTime() : Infinity;
  const eligible = matches.filter(match => new Date(match.playedAt).getTime() < cutoff && [normalizeTeamName(match.homeTeam), normalizeTeamName(match.awayTeam)].includes(team));
  const sameLeague = eligible.filter(match => !config.league || match.league === config.league), useFallback = sameLeague.length < (config.minMatches ?? AlgorithmConfig.poisson.minTeamMatches);
  const selected = useFallback ? eligible : sameLeague, leagueRows = matches.filter(match => !config.league || match.league === config.league);
  const leagueAverage = leagueRows.length ? leagueRows.reduce((sum, match) => sum + match.homeGoals + match.awayGoals, 0) / (leagueRows.length * 2) : 1.3;
  let weightedGoalsFor = 0, weightedGoalsAgainst = 0, weightedMatches = 0;
  for (const match of selected) {
    const home = normalizeTeamName(match.homeTeam) === team, crossLeaguePenalty = config.league && match.league !== config.league ? .5 : 1;
    const weight = calculateTimeDecayWeight(getDaysAgo(match.playedAt, config.cutoffTime ? new Date(config.cutoffTime) : new Date()), config.halfLife) * crossLeaguePenalty;
    weightedGoalsFor += (home ? match.homeGoals : match.awayGoals) * weight; weightedGoalsAgainst += (home ? match.awayGoals : match.homeGoals) * weight; weightedMatches += weight;
  }
  const reliability = Math.min(1, weightedMatches / AlgorithmConfig.poisson.fullReliabilityMatches), safe = weightedMatches || 1, average = leagueAverage || 1.3;
  const rawAttack = weightedMatches ? weightedGoalsFor / safe / average : 1, rawDefense = weightedMatches ? weightedGoalsAgainst / safe / average : 1;
  return {weightedGoalsFor, weightedGoalsAgainst, weightedMatches, matchCount: selected.length, reliability, attackStrength: 1 + (rawAttack - 1) * reliability, defenseWeakness: 1 + (rawDefense - 1) * reliability, sampleWarning: selected.length < (config.minMatches ?? AlgorithmConfig.poisson.minTeamMatches) ? "球队历史样本不足。" : undefined};
}
