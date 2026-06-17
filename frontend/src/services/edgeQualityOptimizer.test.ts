import {describe, expect, it} from "vitest";
import {runEdgeQualityOptimization} from "../algorithm/edgeQualityOptimizer";
import {generateTrueOddsConfigGrid, getDefaultTrueOddsFilterConfig, validateTrueOddsConfig} from "../algorithm/trueOddsConfig";
import {demoBacktestResult} from "../data/backtestData";

describe("edge quality optimizer", () => {
  it("validates default config and generates bounded grid", () => {
    expect(validateTrueOddsConfig(getDefaultTrueOddsFilterConfig())).toHaveLength(0);
    expect(generateTrueOddsConfigGrid(10)).toHaveLength(10);
  });

  it("runs baseline vs true odds variants", () => {
    const result = runEdgeQualityOptimization(demoBacktestResult.records, generateTrueOddsConfigGrid(6), {minSamples: 10});
    expect(result.variantResults).toHaveLength(6);
    expect(result.ranking.length).toBeGreaterThan(0);
    expect(result.blockedAnalysis.blockedCount).toBeGreaterThanOrEqual(0);
    expect(result.bucketPerformance.length).toBeGreaterThan(0);
    expect(result.promotionDecision).toMatch(/KEEP_CURRENT|ENABLE_FILTER_ONLY|NEED_MORE_DATA|REJECT_TRUE_ODDS_FILTER|SHADOW_ONLY/);
  });
});
