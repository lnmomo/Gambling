import {describe, expect, it} from "vitest";
import {calculateEdgeQuality} from "../algorithm/edgeQuality";
import type {ProbabilityUncertainty} from "../types";

const uncertainty: ProbabilityUncertainty = {
  mean: {home: .62, draw: .22, away: .16},
  lower: {home: .58, draw: .18, away: .12},
  upper: {home: .66, draw: .26, away: .20},
  std: {home: .04, draw: .04, away: .04},
  confidence: {home: .7, draw: .7, away: .7},
  methodSpread: {home: .01, draw: .01, away: .01, max: .01},
  modelDisagreement: {home: .02, draw: .02, away: .02},
  sampleReliability: 1,
  overallUncertainty: .3,
  warnings: [],
};

describe("calculateEdgeQuality", () => {
  it("passes a strong edge with positive lowerBoundEV", () => {
    const edge = calculateEdgeQuality("HOME", 2.1, {home: .62, draw: .22, away: .16}, uncertainty, {adaptiveThreshold: .03, methodAgreementScore: 1, externalMarketQuality: "HIGH"});
    expect(edge.lowerBoundEv).toBeGreaterThan(0);
    expect(edge.passesTrueOddsFilter).toBe(true);
  });

  it("blocks when lowerBoundEV is not positive", () => {
    const low = {...uncertainty, lower: {home: .45, draw: .18, away: .12}};
    const edge = calculateEdgeQuality("HOME", 2.1, {home: .52, draw: .26, away: .22}, low, {adaptiveThreshold: .03});
    expect(edge.passesTrueOddsFilter).toBe(false);
    expect(edge.reasons.join(" ")).toContain("lowerBoundEV");
  });
});
