import {describe, expect, it} from "vitest";
import {buildStackingFeatureVector, extractFeatureArray, sanitizeFeatureVector} from "../algorithm/stackingFeatureBuilder";

describe("stacking feature builder", () => {
  it("builds finite defaults and encodes quality/risk", () => { const vector=buildStackingFeatureVector({id:"m",officialMatchId:"o",kickoffTime:"2026-01-01",league:"Cup",context:{isCupOrFriendly:true}},{marketProbability:{home:.5,draw:.3,away:.2},pureModelProbability:{home:.4,draw:.35,away:.25},externalMarketQuality:{available:true,bookmakerCount:3,includedBookmakerCount:3,excludedBookmakerCount:0,averageOverround:.05,maxBookmakerDeviation:.02,officialMarketDeviation:{homeDeviation:0,drawDeviation:0,awayDeviation:0,maxDeviation:.04},staleCount:0,qualityScore:80,qualityLevel:"HIGH",warnings:[]}}); expect(vector.maxMarketPureDeviation).toBeCloseTo(.1); expect(vector.externalMarketQualityLevelEncoded).toBe(1); expect(extractFeatureArray(vector,["marketHomeProb","lambdaHome"]).every(Number.isFinite)).toBe(true); });
  it("sanitizes NaN and Infinity",()=>{const vector=buildStackingFeatureVector({id:"m",officialMatchId:"o",kickoffTime:"2026-01-01",league:"L"},{});const dirty={...vector,marketHomeProb:NaN,officialSpHome:Infinity};const safe=sanitizeFeatureVector(dirty);expect(safe.marketHomeProb).toBeCloseTo(1/3);expect(safe.officialSpHome).toBe(0);});
});
