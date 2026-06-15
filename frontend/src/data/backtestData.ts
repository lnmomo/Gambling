import type {BacktestInputMatch, HistoricalMatch, MatchResult, ThreeWayOdds} from "../types";
import {runWalkForwardBacktest} from "../algorithm/backtestEngine";
import {optimizeTemperature} from "../algorithm/temperatureOptimizer";
import {splitMatchesByTime} from "../algorithm/timeSplit";
import {evaluateStackingAgainstBaseline} from "../algorithm/stackingEvaluator";
import {stackingMockModel} from "./stackingMockModel";

const teams = ["North City", "Harbor United", "River Athletic", "Capital FC"];
const scorePatterns = [[2, 1], [1, 2], [2, 2], [3, 1], [1, 3], [2, 1], [1, 2], [3, 2], [2, 3]] as const;
export const demoHistoricalMatches: HistoricalMatch[] = Array.from({length: 96}, (_, index) => {
  const homeTeam = teams[index % teams.length], rotation = Math.floor(index / teams.length) % 3 + 1, awayTeam = teams[(index + rotation) % teams.length], score = scorePatterns[index % scorePatterns.length];
  return {id: `hist-${index + 1}`, league: index % 3 === 0 ? "Premier Demo" : "National Demo", homeTeam, awayTeam, homeGoals: score[0], awayGoals: score[1], playedAt: new Date(Date.UTC(2024, 0, 1 + index * 5)).toISOString(), matchType: "LEAGUE"};
});
const oddsRows: ThreeWayOdds[] = [{home: 2.41, draw: 3.48, away: 3.17}, {home: 2.83, draw: 3.31, away: 2.65}, {home: 2.00, draw: 3.69, away: 4.11}, {home: 3.28, draw: 3.38, away: 2.34}];
const results: MatchResult["result"][] = ["HOME", "DRAW", "AWAY", "HOME", "HOME", "AWAY", "DRAW", "HOME", "AWAY", "HOME", "DRAW", "AWAY", "HOME", "HOME", "AWAY", "DRAW"];
export const demoBacktestMatches: BacktestInputMatch[] = Array.from({length: 20}, (_, index) => {
  const kickoffTime = new Date(Date.UTC(2025, 5, 1 + index * 6, 12)).toISOString(), officialSp = oddsRows[index % oddsRows.length], result = results[index % results.length], homeTeam = teams[index % teams.length], awayTeam = teams[(index + 1 + index % 2) % teams.length];
  return {id: `bt-${index + 1}`, officialMatchId: `DEMO-${String(index + 1).padStart(3, "0")}`, league: index % 3 === 0 ? "Premier Demo" : "National Demo", homeTeam, awayTeam, kickoffTime, officialSp, closingSp: {home: officialSp.home * (index % 2 ? 1.04 : .96), draw: officialSp.draw * (index % 3 ? 1.02 : .97), away: officialSp.away * (index % 2 ? .95 : 1.05)}, result: {matchId: `bt-${index + 1}`, officialMatchId: `DEMO-${String(index + 1).padStart(3, "0")}`, homeGoals: result === "HOME" ? 2 : result === "DRAW" ? 1 : 0, awayGoals: result === "AWAY" ? 2 : result === "DRAW" ? 1 : 0, result, settledAt: new Date(Date.parse(kickoffTime) + 7_200_000).toISOString()}, externalBookmakerOdds: ["pinnacle", "betfair", "bet365"].map((bookmaker, bookIndex) => ({bookmaker, bookmakerKey: bookmaker, market: "H2H" as const, odds: {home: officialSp.home * (1 + (bookIndex - 1) * .015), draw: officialSp.draw * (1 - (bookIndex - 1) * .01), away: officialSp.away * (1 + (1 - bookIndex) * .012)}, lastUpdate: new Date(Date.parse(kickoffTime) - (20 + bookIndex) * 60_000).toISOString(), source: "Demo historical snapshot"})), context: {lineupKnown: true, dataFreshness: "FRESH", newsReliability: "HIGH"}};
});
const targetHistory: HistoricalMatch[] = demoBacktestMatches.map(match => ({id: `settled-${match.id}`, league: match.league, homeTeam: match.homeTeam, awayTeam: match.awayTeam, homeGoals: match.result!.homeGoals, awayGoals: match.result!.awayGoals, playedAt: match.kickoffTime, matchType: "LEAGUE"}));
export const demoWalkForwardHistory = [...demoHistoricalMatches, ...targetHistory];
const split = splitMatchesByTime(demoBacktestMatches);
export const demoTemperatureOptimization = optimizeTemperature(split.validation, demoWalkForwardHistory);
export const demoBacktestResult = {...runWalkForwardBacktest(demoBacktestMatches, demoWalkForwardHistory), temperatureOptimization: demoTemperatureOptimization};
export const demoStackingEvaluation = evaluateStackingAgainstBaseline(split.test.length ? split.test : demoBacktestMatches, demoWalkForwardHistory, stackingMockModel);
