import type {ModelDisagreement, ThreeWayProbability} from "../types";
const keys = ["home", "draw", "away"] as const;
export function normalizeProbability(p: ThreeWayProbability): ThreeWayProbability {
  const clean = {home: Math.max(0, p.home || 0), draw: Math.max(0, p.draw || 0), away: Math.max(0, p.away || 0)};
  const total = clean.home + clean.draw + clean.away;
  if (!total) throw new Error("概率总和必须大于 0");
  return {home: clean.home / total, draw: clean.draw / total, away: clean.away / total};
}
export function ensembleProbabilities(inputs: {market: ThreeWayProbability; dixonColes: ThreeWayProbability; elo: ThreeWayProbability; ml?: ThreeWayProbability}, weights?: {market: number; dixonColes: number; elo: number; ml?: number}): ThreeWayProbability {
  const selected = weights ?? (inputs.ml ? {market: .35, dixonColes: .30, elo: .15, ml: .20} : {market: .45, dixonColes: .35, elo: .20});
  const weightTotal = selected.market + selected.dixonColes + selected.elo + (inputs.ml ? selected.ml ?? 0 : 0);
  return normalizeProbability({
    home: (inputs.market.home * selected.market + inputs.dixonColes.home * selected.dixonColes + inputs.elo.home * selected.elo + (inputs.ml?.home ?? 0) * (selected.ml ?? 0)) / weightTotal,
    draw: (inputs.market.draw * selected.market + inputs.dixonColes.draw * selected.dixonColes + inputs.elo.draw * selected.elo + (inputs.ml?.draw ?? 0) * (selected.ml ?? 0)) / weightTotal,
    away: (inputs.market.away * selected.market + inputs.dixonColes.away * selected.dixonColes + inputs.elo.away * selected.elo + (inputs.ml?.away ?? 0) * (selected.ml ?? 0)) / weightTotal,
  });
}
export function getDynamicEnsembleWeights(input: {leagueReliability: "LOW" | "MEDIUM" | "HIGH"; eloReliability: "LOW" | "MEDIUM" | "HIGH"; teamStatsReliability: "LOW" | "MEDIUM" | "HIGH"; contextRiskLevel: "LOW" | "MEDIUM" | "HIGH"; marketOverround: number; hasMlModel?: boolean}) {
  const weights: {market: number; dixonColes: number; elo: number; ml?: number} = input.hasMlModel ? {market: .35, dixonColes: .30, elo: .15, ml: .20} : {market: .45, dixonColes: .35, elo: .20};
  if (input.leagueReliability === "LOW") { weights.market += .10; weights.dixonColes -= .05; weights.elo -= .05; }
  if (input.eloReliability === "LOW") { weights.elo -= .10; weights.market += .05; weights.dixonColes += .05; }
  if (input.teamStatsReliability === "LOW") { weights.dixonColes -= .10; weights.market += .10; }
  if (input.contextRiskLevel === "HIGH") { weights.market += .05; weights.dixonColes -= .025; weights.elo -= .025; }
  if (input.marketOverround > .12) { weights.market -= .05; weights.dixonColes += .03; weights.elo += .02; }
  for (const key of Object.keys(weights) as Array<keyof typeof weights>) weights[key] = Math.max(.05, weights[key] ?? .05);
  const total = Object.values(weights).reduce((sum, value) => sum + (value ?? 0), 0);
  for (const key of Object.keys(weights) as Array<keyof typeof weights>) weights[key] = (weights[key] ?? 0) / total;
  return weights;
}
export function getExternalMarketEnsembleWeights(level: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE") {
  const externalMarket = level === "HIGH" ? .25 : level === "MEDIUM" ? .18 : level === "LOW" ? .08 : 0;
  const remaining = 1 - externalMarket, baseRemaining = .35 + .40;
  return {market: remaining * .35 / baseRemaining, externalMarket, pureModel: remaining * .40 / baseRemaining};
}
export function ensembleMarketAndModel(market: ThreeWayProbability, externalMarket: ThreeWayProbability, pureModel: ThreeWayProbability, weights: {market: number; externalMarket: number; pureModel: number}) {
  return normalizeProbability({home: market.home * weights.market + externalMarket.home * weights.externalMarket + pureModel.home * weights.pureModel, draw: market.draw * weights.market + externalMarket.draw * weights.externalMarket + pureModel.draw * weights.pureModel, away: market.away * weights.market + externalMarket.away * weights.externalMarket + pureModel.away * weights.pureModel});
}
export function calculateModelDisagreement(models: ThreeWayProbability[], options: {maxLevel?: "LOW" | "MEDIUM" | "HIGH"} = {}): ModelDisagreement {
  const spread = (key: typeof keys[number]) => Math.max(...models.map(model => model[key])) - Math.min(...models.map(model => model[key]));
  const homeDisagreement = spread("home"), drawDisagreement = spread("draw"), awayDisagreement = spread("away");
  const maxDisagreement = Math.max(homeDisagreement, drawDisagreement, awayDisagreement);
  const rawLevel = maxDisagreement > .12 ? "HIGH" : maxDisagreement > .07 ? "MEDIUM" : "LOW";
  const rank = {LOW: 0, MEDIUM: 1, HIGH: 2} as const;
  const maxLevel = options.maxLevel ?? "HIGH";
  const level = rank[rawLevel] > rank[maxLevel] ? maxLevel : rawLevel;
  return {homeDisagreement, drawDisagreement, awayDisagreement, maxDisagreement, level};
}
