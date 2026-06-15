import {describe, expect, it} from "vitest";
import type {BacktestRecord} from "../types";
import {buildCalibrationTable, calculateExpectedCalibrationError} from "../algorithm/calibrationAnalysis";
const row = (probability: number, hit: boolean): BacktestRecord => ({matchId: String(probability), officialMatchId: "x", league: "L", homeTeam: "A", awayTeam: "B", kickoffTime: "2025-01-01", prediction: {} as BacktestRecord["prediction"], actualResult: "HOME", recommendation: "HOME", selectedProbability: probability, stake: 1, profit: hit ? 1 : -1, hit, brierScore: 0, logLoss: 0, riskLevel: "LOW"});
describe("calibration analysis", () => {
  it("buckets probability and computes hit rate/error", () => { const table = buildCalibrationTable([row(.42, true), row(.44, false)], {bucketSize: .1}); expect(table[0].bucket).toBe("40%-50%"); expect(table[0].actualHitRate).toBe(.5); expect(table[0].calibrationError).toBeCloseTo(.07); });
  it("omits empty buckets", () => expect(buildCalibrationTable([row(.42, true)], {bucketSize: .1})).toHaveLength(1));
  it("computes weighted ECE", () => expect(calculateExpectedCalibrationError([{bucket: "a", lowerBound: 0, upperBound: .5, count: 1, avgPredictedProbability: .4, actualHitRate: 1, calibrationError: .6}, {bucket: "b", lowerBound: .5, upperBound: 1, count: 3, avgPredictedProbability: .7, actualHitRate: .5, calibrationError: .2}])).toBeCloseTo(.3));
});
