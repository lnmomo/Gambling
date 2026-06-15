import type {HistoricalMatch, OfficialMatch, ThreeWayProbability} from "../types";
import {AlgorithmConfig} from "./config";
import {getPastMatchesOnly} from "./timeSplit";
import {normalizeTeamName} from "./teamNameNormalizer";

export const expectedEloResult = (homeElo: number, awayElo: number, homeAdvantage = 65) =>
  1 / (1 + 10 ** (-(homeElo + homeAdvantage - awayElo) / 400));

export function updateElo(homeElo: number, awayElo: number, homeGoals: number, awayGoals: number, options: {matchType?: "LEAGUE" | "CUP" | "FRIENDLY"; homeAdvantage?: number} = {}) {
  const expectedHome = expectedEloResult(homeElo, awayElo, options.homeAdvantage);
  const actualHome = homeGoals > awayGoals ? 1 : homeGoals === awayGoals ? 0.5 : 0;
  const goalDiff = Math.abs(homeGoals - awayGoals);
  const marginMultiplier = goalDiff === 0 ? 1 : Math.min(2, Math.log(goalDiff + 1));
  const k = options.matchType === "CUP" ? 25 : options.matchType === "FRIENDLY" ? 10 : 20;
  const eloChange = k * marginMultiplier * (actualHome - expectedHome);
  return {newHomeElo: homeElo + eloChange, newAwayElo: awayElo - eloChange, expectedHome, actualHome, eloDiff: homeElo + (options.homeAdvantage ?? 65) - awayElo, eloChange};
}

export function calculateElo1X2(homeElo: number, awayElo: number, homeAdvantage = 65): ThreeWayProbability {
  const eloDiff = homeElo + homeAdvantage - awayElo;
  const pHomeNoDraw = expectedEloResult(homeElo, awayElo, homeAdvantage);
  const pDraw = Math.min(0.32, Math.max(0.12, 0.27 * Math.exp(-Math.abs(eloDiff) / 500)));
  return {home: (1 - pDraw) * pHomeNoDraw, draw: pDraw, away: (1 - pDraw) * (1 - pHomeNoDraw)};
}
export function buildEloRatings(matches: HistoricalMatch[], options: {initialElo?: number; homeAdvantage?: number} = {}) {
  const initial = options.initialElo ?? AlgorithmConfig.elo.initialElo, ratings: Record<string, number> = {}, history: Array<Record<string, string | number>> = [];
  for (const match of [...matches].sort((a, b) => new Date(a.playedAt).getTime() - new Date(b.playedAt).getTime())) {
    const homeTeam = normalizeTeamName(match.homeTeam), awayTeam = normalizeTeamName(match.awayTeam), oldHomeElo = ratings[homeTeam] ?? initial, oldAwayElo = ratings[awayTeam] ?? initial;
    const matchType=match.matchType==="INTERNATIONAL"||match.matchType==="UNKNOWN"?"LEAGUE":match.matchType;const result = updateElo(oldHomeElo, oldAwayElo, match.homeGoals, match.awayGoals, {matchType, homeAdvantage: options.homeAdvantage}); ratings[homeTeam] = result.newHomeElo; ratings[awayTeam] = result.newAwayElo;
    history.push({matchId: match.id, date: match.playedAt, homeTeam, awayTeam, oldHomeElo, oldAwayElo, newHomeElo: result.newHomeElo, newAwayElo: result.newAwayElo, eloChange: result.eloChange});
  }
  return {ratings, history};
}
export function getEloBeforeMatch(matches: HistoricalMatch[], target: Pick<OfficialMatch, "homeTeam" | "awayTeam" | "kickoffTime">) {
  const past = getPastMatchesOnly(matches, target.kickoffTime), built = buildEloRatings(past), home = normalizeTeamName(target.homeTeam), away = normalizeTeamName(target.awayTeam);
  const count = (team: string) => past.filter(match => [normalizeTeamName(match.homeTeam), normalizeTeamName(match.awayTeam)].includes(team)).length, homeMatchCount = count(home), awayMatchCount = count(away);
  const reliability: "LOW" | "MEDIUM" | "HIGH" = homeMatchCount >= 20 && awayMatchCount >= 20 ? "HIGH" : homeMatchCount >= 10 && awayMatchCount >= 10 ? "MEDIUM" : "LOW";
  return {homeElo: built.ratings[home] ?? AlgorithmConfig.elo.initialElo, awayElo: built.ratings[away] ?? AlgorithmConfig.elo.initialElo, homeMatchCount, awayMatchCount, reliability};
}
