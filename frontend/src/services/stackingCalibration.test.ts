import {describe, expect, it} from "vitest";
import {calibrateStackingProbability,evaluateStackingCalibration} from "../algorithm/stackingCalibration";
describe("stacking calibration",()=>{it("keeps probabilities normalized",()=>{const p=calibrateStackingProbability({home:.6,draw:.25,away:.15},1.1);expect(p.home+p.draw+p.away).toBeCloseTo(1)});it("calculates finite quality metrics",()=>{const result=evaluateStackingCalibration([{probability:{home:.6,draw:.25,away:.15},label:"HOME"}]);expect(Object.values(result).every(Number.isFinite)).toBe(true)});});
