import {describe, expect, it} from "vitest";
import {trainStackingModelWithTimeSplit} from "../algorithm/stackingTrainer";
import {demoBacktestMatches,demoWalkForwardHistory} from "../data/backtestData";
describe("stacking trainer",()=>{it("uses chronological split and blocks small training sets",()=>{const result=trainStackingModelWithTimeSplit(demoBacktestMatches,demoWalkForwardHistory);expect(result.coefficients).toBeUndefined();expect(result.warnings[0]).toContain("样本不足");const all=[...result.trainExamples,...result.validationExamples,...result.testExamples];expect(all.map(x=>x.features.kickoffTime)).toEqual(all.map(x=>x.features.kickoffTime).sort());expect(all.every(x=>x.sampleWeight>0&&x.sampleWeight<=1)).toBe(true)});});
