import {describe, expect, it} from "vitest";
import {calculateMultiDevigProbabilities} from "../algorithm/multiDevig";

describe("calculateMultiDevigProbabilities", () => {
  it("calculates valid probabilities for every devig method", () => {
    const result = calculateMultiDevigProbabilities({home: 2.1, draw: 3.2, away: 3.4});
    expect(result.recommendedMethod).toBe("POWER");
    expect(result.methodAgreementScore).toBeGreaterThan(0);
    Object.values(result.methods).forEach(row => {
      expect(row.valid).toBe(true);
      expect(row.probability.home + row.probability.draw + row.probability.away).toBeCloseTo(1, 8);
      expect(row.fairOdds.home).toBeGreaterThan(1);
    });
  });

  it("handles invalid odds without NaN", () => {
    const result = calculateMultiDevigProbabilities({home: 1, draw: 0, away: 3.4});
    expect(result.warnings).toContain("invalid odds");
    expect(Object.values(result.methods).every(row => !row.valid)).toBe(true);
    expect(result.recommendedProbability.home + result.recommendedProbability.draw + result.recommendedProbability.away).toBeCloseTo(1, 8);
  });
});
