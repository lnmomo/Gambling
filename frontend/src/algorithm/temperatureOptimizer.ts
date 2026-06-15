import type {BacktestInputMatch, HistoricalMatch, TemperatureOptimizationResult} from "../types";
import {runWalkForwardBacktest} from "./backtestEngine";

export const DEFAULT_TEMPERATURE_CANDIDATES = [.90, .95, 1, 1.05, 1.08, 1.10, 1.15, 1.20, 1.25, 1.30];
export function optimizeTemperature(validationMatches: BacktestInputMatch[], historicalMatches: HistoricalMatch[], options: {candidates?: number[]; bankroll?: number} = {}): TemperatureOptimizationResult {
  const previousTemperature = 1.08, candidates = options.candidates ?? DEFAULT_TEMPERATURE_CANDIDATES;
  if (validationMatches.filter(match => match.result).length < 3) return {candidates: [], bestTemperature: previousTemperature, bestLogLoss: 0, previousTemperature, improvement: 0};
  const results = candidates.map(temperature => { const metrics = runWalkForwardBacktest(validationMatches, historicalMatches, {temperature, bankroll: options.bankroll}).metrics; return {temperature, logLoss: metrics.logLoss, brierScore: metrics.brierScore, calibrationError: metrics.calibrationError}; });
  const best = results.reduce((current, row) => row.logLoss < current.logLoss ? row : current), current = results.find(row => row.temperature === previousTemperature);
  return {candidates: results, bestTemperature: best.temperature, bestLogLoss: best.logLoss, previousTemperature, improvement: Math.max(0, (current?.logLoss ?? best.logLoss) - best.logLoss)};
}
