import type {BacktestMetrics, BacktestRecord, ThreeWayProbability} from "../types";
import {buildCalibrationTable, calculateExpectedCalibrationError} from "./calibrationAnalysis";

const mean = (values: number[]) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
export function calculateBrierScore(probability: ThreeWayProbability, actualResult: "HOME" | "DRAW" | "AWAY") {
  const actual = {HOME: [1, 0, 0], DRAW: [0, 1, 0], AWAY: [0, 0, 1]}[actualResult];
  return ([probability.home, probability.draw, probability.away].reduce((sum, value, index) => sum + (value - actual[index]) ** 2, 0)) / 3;
}
export function calculateLogLoss(probability: ThreeWayProbability, actualResult: "HOME" | "DRAW" | "AWAY") {
  const value = actualResult === "HOME" ? probability.home : actualResult === "DRAW" ? probability.draw : probability.away;
  return -Math.log(Math.min(1 - 1e-15, Math.max(1e-15, value)));
}
export function calculateMaxDrawdown(records: BacktestRecord[]) {
  let equity = 0, peak = 0, maxDrawdown = 0;
  for (const record of [...records].sort((a, b) => Date.parse(a.kickoffTime) - Date.parse(b.kickoffTime))) { equity += record.profit; peak = Math.max(peak, equity); maxDrawdown = Math.max(maxDrawdown, peak - equity); }
  return maxDrawdown;
}
export function calculateBacktestMetrics(records: BacktestRecord[]): BacktestMetrics {
  const bets = records.filter(record => record.recommendation !== "NO_BET" && record.hit !== null), settled = records.filter(record => record.actualResult), clvRows = bets.filter(record => Number.isFinite(record.clv));
  const totalStake = bets.reduce((sum, record) => sum + record.stake, 0), totalProfit = bets.reduce((sum, record) => sum + record.profit, 0), hitCount = bets.filter(record => record.hit).length;
  const calibrationTable = buildCalibrationTable(records, {useSelectedOnly: true});
  return {totalMatches: records.length, totalBets: bets.length, noBetCount: records.filter(record => record.recommendation === "NO_BET").length, noBetRatio: records.length ? records.filter(record => record.recommendation === "NO_BET").length / records.length : 0, hitCount, hitRate: bets.length ? hitCount / bets.length : 0, totalStake, totalProfit, roi: totalStake ? totalProfit / totalStake : 0, maxDrawdown: calculateMaxDrawdown(records), averageEv: mean(bets.flatMap(record => record.ev === undefined ? [] : [record.ev])), averageClv: mean(clvRows.map(record => record.clv!)), positiveClvRate: clvRows.length ? clvRows.filter(record => record.clv! > 0).length / clvRows.length : 0, brierScore: mean(settled.map(record => record.brierScore)), logLoss: mean(settled.map(record => record.logLoss)), averagePredictedProbability: mean(bets.flatMap(record => record.selectedProbability === undefined ? [] : [record.selectedProbability])), averageActualHitRate: bets.length ? hitCount / bets.length : 0, calibrationError: calculateExpectedCalibrationError(calibrationTable)};
}
