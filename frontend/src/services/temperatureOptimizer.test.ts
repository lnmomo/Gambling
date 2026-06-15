import {describe, expect, it} from "vitest";
import {optimizeTemperature} from "../algorithm/temperatureOptimizer";
import {demoBacktestMatches, demoWalkForwardHistory} from "../data/backtestData";
describe("temperature optimizer", () => { it("evaluates all candidates and chooses minimum log loss", () => { const candidates = [1, 1.08, 1.2], result = optimizeTemperature(demoBacktestMatches.slice(0, 6), demoWalkForwardHistory, {candidates}); expect(result.candidates).toHaveLength(3); expect(result.bestLogLoss).toBe(Math.min(...result.candidates.map(row => row.logLoss))); }); it("falls back to current temperature for insufficient validation data", () => expect(optimizeTemperature(demoBacktestMatches.slice(0, 2), demoWalkForwardHistory).bestTemperature).toBe(1.08)); });
