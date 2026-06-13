export * from "../algorithm/probabilityEngine";
export {calculateDixonColes1X2} from "../algorithm/dixonColesModel";
export {calculateElo1X2 as calculateElo1x2} from "../algorithm/eloModel";
export {calculateModelDisagreement as calculateModelDisagreementDetails} from "../algorithm/ensembleModel";
export {runCriticCheck, calculateDynamicEvThreshold} from "../algorithm/criticRules";

import type {MatchContext, ModelDisagreement, OfficialMatch, ThreeWayEv, ThreeWayProbability} from "../types";
import {calculateModelDisagreement as details, ensembleProbabilities as ensemble} from "../algorithm/ensembleModel";
import {runCriticCheck} from "../algorithm/criticRules";
import {calculateDixonColes1X2} from "../algorithm/dixonColesModel";

export function calculatePoisson1x2(lambdaHome: number, lambdaAway: number) { return calculateDixonColes1X2(lambdaHome, lambdaAway).probability; }

export function ensembleProbabilities(market: ThreeWayProbability, poisson: ThreeWayProbability, elo: ThreeWayProbability, weights = {market: .45, poisson: .35, elo: .20}) {
  return ensemble({market, dixonColes: poisson, elo}, {market: weights.market, dixonColes: weights.poisson, elo: weights.elo});
}
export function calculateModelDisagreement(...models: ThreeWayProbability[]): number { return details(models).maxDisagreement; }
export function runCriticChecks(match: Pick<OfficialMatch, "officialMatchId" | "status" | "officialSp" | "updatedAt">, draft: {finalProbability: ThreeWayProbability; ev: ThreeWayEv; modelDisagreement: number | ModelDisagreement}, context: MatchContext = {}) {
  const disagreement = typeof draft.modelDisagreement === "number" ? {homeDisagreement: draft.modelDisagreement, drawDisagreement: draft.modelDisagreement, awayDisagreement: draft.modelDisagreement, maxDisagreement: draft.modelDisagreement, level: draft.modelDisagreement > .12 ? "HIGH" as const : draft.modelDisagreement > .07 ? "MEDIUM" as const : "LOW" as const} : draft.modelDisagreement;
  const effectiveContext = {...context};
  const age = Date.now() - new Date(match.updatedAt).getTime();
  if (!Number.isFinite(age) || age > 10 * 60_000) effectiveContext.dataFreshness = "STALE";
  const report = runCriticCheck(match, {...draft, modelDisagreement: disagreement}, effectiveContext, .05);
  const reasons = [...report.reasons];
  if (effectiveContext.dataFreshness === "STALE") reasons.push("官方赔率更新时间超过10分钟");
  if (Math.max(...Object.values(draft.ev)) < .05) reasons.push("最高 EV 低于5%阈值");
  return {passed: reasons.length === 0, reasons: [...new Set(reasons)]};
}
