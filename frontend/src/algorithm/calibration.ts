import type {ThreeWayProbability} from "../types";
import {AlgorithmConfig} from "./config";
import {normalizeProbability} from "./ensembleModel";
export function calibrateProbabilities(probability: ThreeWayProbability, options: {method?: "none" | "temperature"; temperature?: number} = {}): ThreeWayProbability {
  if (options.method === "none") return normalizeProbability(probability);
  const temperature = Math.max(.1, options.temperature ?? AlgorithmConfig.calibration.defaultTemperature);
  const scores = [probability.home, probability.draw, probability.away].map(value => Math.log(Math.max(value, 1e-12)) / temperature), max = Math.max(...scores);
  const exp = scores.map(score => Math.exp(score - max)), total = exp.reduce((a, b) => a + b, 0);
  return {home: exp[0] / total, draw: exp[1] / total, away: exp[2] / total};
}
export function estimateTemperatureFromValidation(predictions: ThreeWayProbability[], actualResults: Array<"HOME" | "DRAW" | "AWAY">) {
  if (!predictions.length || predictions.length !== actualResults.length) return AlgorithmConfig.calibration.defaultTemperature;
  const candidates = [.90, 1, 1.05, 1.08, 1.10, 1.15, 1.20, 1.25, 1.30];
  return candidates.reduce((best, temperature) => {
    const loss = predictions.reduce((sum, prediction, index) => { const p = calibrateProbabilities(prediction, {method: "temperature", temperature}); const value = actualResults[index] === "HOME" ? p.home : actualResults[index] === "DRAW" ? p.draw : p.away; return sum - Math.log(Math.max(value, 1e-15)); }, 0) / predictions.length;
    return loss < best.loss ? {temperature, loss} : best;
  }, {temperature: 1.08, loss: Infinity}).temperature;
}
