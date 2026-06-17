import type {TrueOddsFilterConfig} from "../types";

export const getDefaultTrueOddsFilterConfig = (): TrueOddsFilterConfig => ({
  configId: "default-filter-only", name: "Default FILTER_ONLY", lowerBoundEvMin: 0, edgeQualityMinScore: 55,
  allowedEdgeQualityLevels: ["MEDIUM", "HIGH"], uncertaintyZ: 1, minMethodAgreementScore: .55, baseEvThreshold: .03,
  drawExtraThreshold: .01, highOddsExtraThreshold: .02, lowOddsExtraThreshold: .015,
  requirePositiveExpectedClv: false, minClvWinProbability: null, mode: "FILTER_ONLY", warnings: [],
});

export function generateTrueOddsConfigGrid(maxConfigs = 24): TrueOddsFilterConfig[] {
  const base = getDefaultTrueOddsFilterConfig();
  const named: TrueOddsFilterConfig[] = [
    base,
    {...base, configId: "conservative", name: "Conservative", lowerBoundEvMin: .01, edgeQualityMinScore: 65, uncertaintyZ: 1.25, minMethodAgreementScore: .65},
    {...base, configId: "aggressive", name: "Aggressive", lowerBoundEvMin: 0, edgeQualityMinScore: 50, uncertaintyZ: .75, minMethodAgreementScore: .45},
    {...base, configId: "draw-strict", name: "Draw Strict", drawExtraThreshold: .02, edgeQualityMinScore: 60},
    {...base, configId: "high-agreement", name: "High Agreement", minMethodAgreementScore: .75, edgeQualityMinScore: 60},
  ];
  const grid = [...named], lowers = [0, .005, .01, .015], scores = [55, 60, 65, 70], zs = [.75, 1, 1.25], agreements = [.45, .55, .65, .75];
  outer: for (const lower of lowers) for (const score of scores) for (const z of zs) for (const agreement of agreements) {
    grid.push({...base, configId: `grid-${grid.length}`, name: `Grid ${grid.length}`, lowerBoundEvMin: lower, edgeQualityMinScore: score, uncertaintyZ: z, minMethodAgreementScore: agreement});
    if (grid.length >= maxConfigs) break outer;
  }
  return grid.slice(0, maxConfigs);
}

export function validateTrueOddsConfig(config: TrueOddsFilterConfig): string[] {
  const warnings:string[] = [];
  if (config.mode === "ADJUST_PROBABILITY") warnings.push("ADJUST_PROBABILITY must not be enabled automatically.");
  if (config.lowerBoundEvMin < 0 || config.lowerBoundEvMin > .05) warnings.push("lowerBoundEvMin out of range.");
  if (config.edgeQualityMinScore < 35 || config.edgeQualityMinScore > 90) warnings.push("edgeQualityMinScore out of range.");
  if (config.uncertaintyZ < .5 || config.uncertaintyZ > 2) warnings.push("uncertaintyZ out of range.");
  if (config.minMethodAgreementScore < 0 || config.minMethodAgreementScore > 1) warnings.push("minMethodAgreementScore out of range.");
  return warnings;
}
