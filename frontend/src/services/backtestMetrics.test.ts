import {describe, expect, it} from "vitest";
import type {BacktestRecord} from "../types";
import {calculateBacktestMetrics, calculateBrierScore, calculateLogLoss, calculateMaxDrawdown} from "../algorithm/backtestMetrics";

const record = (values: Partial<BacktestRecord>): BacktestRecord => ({matchId: "x", officialMatchId: "x", league: "L", homeTeam: "A", awayTeam: "B", kickoffTime: "2025-01-01T00:00:00Z", prediction: {} as BacktestRecord["prediction"], recommendation: "HOME", stake: 1, profit: 0, hit: false, brierScore: .2, logLoss: .8, riskLevel: "LOW", ...values});
describe("backtest metrics", () => {
  it("calculates three-way Brier score", () => expect(calculateBrierScore({home: .6, draw: .25, away: .15}, "HOME")).toBeCloseTo((.16 + .0625 + .0225) / 3));
  it("calculates log loss", () => expect(calculateLogLoss({home: .6, draw: .25, away: .15}, "HOME")).toBeCloseTo(-Math.log(.6)));
  it("calculates ROI and excludes NO_BET", () => { const metrics = calculateBacktestMetrics([record({profit: 1, hit: true}), record({matchId: "n", recommendation: "NO_BET", stake: 0, profit: 0, hit: null})]); expect(metrics.totalBets).toBe(1); expect(metrics.roi).toBe(1); expect(metrics.noBetRatio).toBe(.5); });
  it("calculates maximum drawdown in time order", () => expect(calculateMaxDrawdown([record({matchId: "1", profit: 2}), record({matchId: "2", kickoffTime: "2025-01-02T00:00:00Z", profit: -3})])).toBe(3));
  it("never returns NaN without bets", () => { const metrics = calculateBacktestMetrics([record({recommendation: "NO_BET", stake: 0, hit: null})]); expect(Object.values(metrics).every(Number.isFinite)).toBe(true); });
});
