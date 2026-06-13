import type {RecommendationType, ThreeWayProbability} from "../types";
import type {HistoricalMatch, MatchContext, OfficialMatch} from "../types";
import {calculateMatchPrediction} from "./probabilityEngine";
import {analyzePredictionErrors} from "./errorAnalysis";
export interface BacktestMetricRecord {matchId: string; recommendation: RecommendationType; odds: number; probability: number; probabilities?: ThreeWayProbability; ev: number; result: "HOME" | "DRAW" | "AWAY"; stake: number; profit: number; closingOdds: number}
export function calculateBacktestMetrics(records: BacktestMetricRecord[]) {
  const bets = records.filter(record => record.recommendation !== "NO_BET");
  const totalStake = bets.reduce((sum, record) => sum + record.stake, 0);
  const profit = bets.reduce((sum, record) => sum + record.profit, 0);
  let equity = 0, peak = 0, maxDrawdown = 0;
  for (const record of bets) { equity += record.profit; peak = Math.max(peak, equity); maxDrawdown = Math.max(maxDrawdown, peak - equity); }
  const average = (values: number[]) => values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
  const brier = records.map(record => {
    const p = record.probabilities ?? {home: record.probability, draw: (1 - record.probability) / 2, away: (1 - record.probability) / 2};
    return (["HOME", "DRAW", "AWAY"] as const).reduce((sum, result, index) => sum + ([p.home, p.draw, p.away][index] - (record.result === result ? 1 : 0)) ** 2, 0);
  });
  const logLoss = records.map(record => {
    const p = record.probabilities;
    const value = p ? (record.result === "HOME" ? p.home : record.result === "DRAW" ? p.draw : p.away) : record.probability;
    return -Math.log(Math.min(1 - 1e-15, Math.max(1e-15, value)));
  });
  return {totalBets: bets.length, hitRate: bets.length ? bets.filter(record => record.profit > 0).length / bets.length : 0, roi: totalStake ? profit / totalStake : 0, profit, maxDrawdown, averageEv: average(bets.map(record => record.ev)), averageClosingLineValue: average(bets.filter(record => record.closingOdds > 1).map(record => record.odds / record.closingOdds - 1)), brierScore: average(brier), logLoss: average(logLoss), noBetRatio: records.length ? (records.length - bets.length) / records.length : 0};
}
export function runWalkForwardBacktest(matches: Array<OfficialMatch & {result?: "HOME" | "DRAW" | "AWAY"; closingOdds?: number}>, historicalMatches: HistoricalMatch[], contexts: Record<string, MatchContext>, options: {bankroll?: number} = {}) {
  const records: BacktestMetricRecord[] = matches.filter(match => match.result).sort((a, b) => new Date(a.kickoffTime).getTime() - new Date(b.kickoffTime).getTime()).map(match => {
    const prediction = calculateMatchPrediction(match, historicalMatches, contexts[match.id] ?? {}, options.bankroll ?? 10_000), action = prediction.recommendation, probability = prediction.recommendedProbability ?? Math.max(...Object.values(prediction.finalProbability)), odds = prediction.recommendedSp ?? 0, won = action !== "NO_BET" && action === match.result, stake = prediction.suggestedStake;
    return {matchId: match.id, recommendation: action, odds, probability, probabilities: prediction.finalProbability, ev: prediction.recommendedEv ?? 0, result: match.result!, stake, profit: action === "NO_BET" ? 0 : won ? stake * (odds - 1) : -stake, closingOdds: match.closingOdds ?? odds};
  });
  return {records, metrics: calculateBacktestMetrics(records), errorAnalysis: analyzePredictionErrors(records)};
}
