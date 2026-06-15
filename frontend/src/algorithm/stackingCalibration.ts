import type {StackingTrainingExample, ThreeWayProbability} from "../types";
import {calibrateProbabilities} from "./calibration";
import {calculateBrierScore, calculateLogLoss} from "./backtestMetrics";

export const calibrateStackingProbability = (probability: ThreeWayProbability, temperature = 1) => calibrateProbabilities(probability, {method: "temperature", temperature});
export function evaluateStackingCalibration(rows: Array<{probability: ThreeWayProbability; label: StackingTrainingExample["label"]}>) {
  if (!rows.length) return {logLoss: 0, brierScore: 0, calibrationError: 0};
  const logLoss = rows.reduce((sum, row) => sum + calculateLogLoss(row.probability, row.label), 0) / rows.length;
  const brierScore = rows.reduce((sum, row) => sum + calculateBrierScore(row.probability, row.label), 0) / rows.length;
  const calibrationError = rows.reduce((sum, row) => { const values = [row.probability.home, row.probability.draw, row.probability.away], confidence = Math.max(...values), predicted = values.indexOf(confidence), actual = row.label === "HOME" ? 0 : row.label === "DRAW" ? 1 : 2; return sum + Math.abs(confidence - (predicted === actual ? 1 : 0)); }, 0) / rows.length;
  return {logLoss, brierScore, calibrationError};
}
