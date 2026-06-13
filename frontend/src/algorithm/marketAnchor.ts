import type {MarketDeviation, ThreeWayProbability} from "../types";
import {AlgorithmConfig} from "./config";
import {normalizeProbability} from "./ensembleModel";
export function calculateMarketDeviation(market: ThreeWayProbability, model: ThreeWayProbability): MarketDeviation {
  const homeDeviation = Math.abs(model.home - market.home), drawDeviation = Math.abs(model.draw - market.draw), awayDeviation = Math.abs(model.away - market.away);
  return {homeDeviation, drawDeviation, awayDeviation, maxDeviation: Math.max(homeDeviation, drawDeviation, awayDeviation)};
}
export function applyMarketAnchor(model: ThreeWayProbability, market: ThreeWayProbability, options: {maxDeviation?: number; anchorStrength?: number} = {}) {
  const maxDeviation = options.maxDeviation ?? AlgorithmConfig.marketGuard.anchorDeviation, anchorStrength = options.anchorStrength ?? AlgorithmConfig.marketGuard.anchorStrength;
  const deviationBefore = calculateMarketDeviation(market, model);
  if (deviationBefore.maxDeviation <= maxDeviation) return {probability: normalizeProbability(model), deviationBefore, deviationAfter: deviationBefore, anchored: false};
  const probability = normalizeProbability({home: model.home * (1 - anchorStrength) + market.home * anchorStrength, draw: model.draw * (1 - anchorStrength) + market.draw * anchorStrength, away: model.away * (1 - anchorStrength) + market.away * anchorStrength});
  return {probability, deviationBefore, deviationAfter: calculateMarketDeviation(market, probability), anchored: true, warning: "模型概率与市场存在明显偏离，已进行市场锚定。"};
}
