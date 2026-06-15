import {describe, expect, it} from "vitest";
import {evaluateStackingAgainstBaseline} from "../algorithm/stackingEvaluator";
import {demoBacktestMatches,demoWalkForwardHistory} from "../data/backtestData";
import {stackingMockModel} from "../data/stackingMockModel";
describe("stacking evaluator",()=>{it("compares baseline and stacking by league",()=>{const result=evaluateStackingAgainstBaseline(demoBacktestMatches.slice(0,4),demoWalkForwardHistory,stackingMockModel);expect(result.baselineMetrics.totalMatches).toBe(4);expect(result.stackingMetrics.totalMatches).toBe(4);expect(result.logLossImprovement).toBeCloseTo(result.baselineMetrics.logLoss-result.stackingMetrics.logLoss);expect(result.byLeague.length).toBeGreaterThan(0);expect(result.summary.length).toBeGreaterThan(0)});});
