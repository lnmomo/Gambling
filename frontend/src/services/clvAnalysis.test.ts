import {describe, expect, it} from "vitest";
import type {BacktestRecord} from "../types";
import {analyzeClv, calculateClv} from "../algorithm/clvAnalysis";
const record = (clv?: number): BacktestRecord => ({matchId: "x", officialMatchId: "x", league: "L", homeTeam: "A", awayTeam: "B", kickoffTime: "2025-01-01", prediction: {} as BacktestRecord["prediction"], recommendation: "HOME", stake: 1, profit: 0, hit: false, clv, brierScore: 0, logLoss: 0, riskLevel: "LOW"});
describe("CLV", () => { it("uses selected SP divided by closing SP", () => expect(calculateClv(2.2, 1.95)).toBeCloseTo(.128205)); it("detects positive CLV", () => expect(analyzeClv([record(.1), record(-.05)]).positiveClvRate).toBe(.5)); it("ignores missing closing SP", () => expect(analyzeClv([record()]).averageClv).toBe(0)); });
