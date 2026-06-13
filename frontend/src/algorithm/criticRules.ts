import type {CriticReport, MarketDeviation, MatchContext, MatchPrediction, MatchStatus, ModelDisagreement, OfficialMatch, RecommendationType, RiskLevel, ThreeWayEv, ThreeWayProbability} from "../types";
import {AlgorithmConfig} from "./config";

export interface DynamicThresholdInput {baseThreshold?: number; riskLevel: RiskLevel; dataFreshness: "FRESH" | "STALE"; modelDisagreement: ModelDisagreement; lineupKnown: boolean; minutesToKickoff?: number; homeMatchCount?: number; awayMatchCount?: number; marketDeviation?: MarketDeviation; selectedOdds?: number; competitionType?: "LEAGUE" | "CUP" | "FRIENDLY" | "UNKNOWN"; matchStatus?: MatchStatus}
export function calculateDynamicEvThreshold(input: DynamicThresholdInput) {
  let threshold = input.baseThreshold ?? AlgorithmConfig.critic.baseEvThreshold;
  threshold += input.riskLevel === "HIGH" ? .035 : input.riskLevel === "MEDIUM" ? .015 : 0;
  threshold += input.dataFreshness === "STALE" ? .025 : 0;
  threshold += input.modelDisagreement.level === "HIGH" ? .05 : input.modelDisagreement.level === "MEDIUM" ? .015 : 0;
  if (!input.lineupKnown) threshold += .015 + ((input.minutesToKickoff ?? Infinity) < 120 ? .02 : 0);
  const minMatches = Math.min(input.homeMatchCount ?? 20, input.awayMatchCount ?? 20);
  if (minMatches < 5) return Infinity; if (minMatches < 10) threshold += .035; else if (minMatches < 20) threshold += .015;
  const deviation = input.marketDeviation?.maxDeviation ?? 0;
  if (deviation > .18) return Infinity; if (deviation > .12) threshold += .025; else if (deviation > .08) threshold += .01;
  const odds = input.selectedOdds ?? 2;
  if (odds < 1.25) return Infinity; if (odds < 1.30) threshold += .03; else if (odds < 1.50) threshold += .015;
  threshold += input.competitionType === "FRIENDLY" ? .035 : input.competitionType === "CUP" ? .015 : input.competitionType === "UNKNOWN" ? .025 : 0;
  return Math.max(.04, threshold);
}
const actionRows = (p: ThreeWayProbability, ev: ThreeWayEv, sp: OfficialMatch["officialSp"]) => [
  {action: "HOME" as const, probability: p.home, ev: ev.home, odds: sp.home}, {action: "DRAW" as const, probability: p.draw, ev: ev.draw, odds: sp.draw}, {action: "AWAY" as const, probability: p.away, ev: ev.away, odds: sp.away},
].sort((a, b) => b.ev - a.ev);
export function runCriticCheck(match: Pick<OfficialMatch, "officialMatchId" | "status" | "officialSp">, draft: {finalProbability: ThreeWayProbability; ev: ThreeWayEv; modelDisagreement: ModelDisagreement; marketDeviation?: MarketDeviation; homeMatchCount?: number; awayMatchCount?: number}, context: MatchContext, dynamicEvThreshold: number): CriticReport {
  const reasons: string[] = [], warnings: string[] = [], best = actionRows(draft.finalProbability, draft.ev, match.officialSp)[0];
  if (!match.officialMatchId) reasons.push("缺少官方比赛 ID，不进入模型推荐。");
  if (["CANCELLED", "POSTPONED", "CLOSED", "FINISHED"].includes(match.status)) reasons.push("比赛已取消、延期、停售或结束。");
  if (Object.values(match.officialSp).some(value => !Number.isFinite(value) || value <= 1)) reasons.push("官方胜平负 SP 无效。");
  if (Math.abs(Object.values(draft.finalProbability).reduce((a, b) => a + b, 0) - 1) > .001) reasons.push("最终概率未归一化。");
  if (draft.modelDisagreement.level === "HIGH") reasons.push("模型分歧过高，禁止推荐。");
  const minSamples = Math.min(draft.homeMatchCount ?? 20, draft.awayMatchCount ?? 20);
  if (minSamples < 5) reasons.push("球队历史样本严重不足。"); else if (minSamples < 10) warnings.push("球队历史样本不足。");
  const deviation = draft.marketDeviation?.maxDeviation ?? 0;
  if (deviation > AlgorithmConfig.marketGuard.noBetDeviation) reasons.push("模型概率与市场隐含概率偏离过大。"); else if (deviation > AlgorithmConfig.marketGuard.anchorDeviation) warnings.push("模型概率与市场存在明显偏离，已进行市场锚定。");
  const maxProbability = Math.max(...Object.values(draft.finalProbability));
  if (maxProbability > AlgorithmConfig.critic.maxAllowedProbability) reasons.push("最终概率异常过高。"); else if (maxProbability > AlgorithmConfig.critic.highProbabilityWarning) warnings.push("最终概率过高，可能存在过度自信。");
  if (best.odds < AlgorithmConfig.critic.minRecommendedOdds) reasons.push("赔率过低，风险收益比不足。");
  if (!Number.isFinite(dynamicEvThreshold) || best.ev < dynamicEvThreshold) reasons.push(`最高 EV ${(best.ev * 100).toFixed(2)}% 未超过动态阈值 ${Number.isFinite(dynamicEvThreshold) ? `${(dynamicEvThreshold * 100).toFixed(2)}%` : "（禁止推荐）"}。`);
  if (best.action === "DRAW" && (best.ev < dynamicEvThreshold + .02 || draft.modelDisagreement.level === "HIGH" || (draft.marketDeviation?.drawDeviation ?? 0) > .12)) reasons.push("平局推荐未满足额外安全边际。");
  if (context.dataFreshness === "STALE") reasons.push("数据已过期。");
  if (context.newsReliability === "LOW") warnings.push("新闻可信度偏低。");
  if (context.lineupKnown === false) warnings.push("首发阵容未知，已提高 EV 门槛。");
  if (context.riskLimitTriggered) reasons.push("已触发风险额度上限。");
  const riskLevel: RiskLevel = reasons.length >= 2 || draft.modelDisagreement.level === "HIGH" ? "HIGH" : warnings.length || reasons.length ? "MEDIUM" : "LOW";
  const confidenceLevel = riskLevel === "LOW" && draft.modelDisagreement.level === "LOW" ? "A" : riskLevel !== "HIGH" && draft.modelDisagreement.level !== "HIGH" ? "B" : reasons.length <= 1 ? "C" : "D";
  const passed = reasons.length === 0;
  return {passed, finalAction: passed ? best.action : "NO_BET", reasons: [...new Set(reasons)], warnings: [...new Set(warnings)], dynamicEvThreshold, confidenceLevel, riskLevel};
}
export function limitDailyRecommendations(predictions: MatchPrediction[], maxRecommendations = AlgorithmConfig.critic.maxDailyRecommendations) {
  const ranked = predictions.filter(p => p.criticReport.passed && p.recommendation !== "NO_BET").sort((a, b) => ((b.recommendedEv ?? 0) - b.dynamicEvThreshold) - ((a.recommendedEv ?? 0) - a.dynamicEvThreshold) || a.modelDisagreement.maxDisagreement - b.modelDisagreement.maxDisagreement);
  const allowed = new Set(ranked.slice(0, maxRecommendations).map(p => p.matchId));
  return predictions.map(p => allowed.has(p.matchId) || p.recommendation === "NO_BET" ? p : {...p, recommendation: "NO_BET" as const, suggestedStake: 0, stakeFraction: 0, recommendedProbability: null, recommendedSp: null, recommendedEv: null, criticPassed: false, criticReasons: [...p.criticReasons, "超出单日推荐数量上限。"], criticReport: {...p.criticReport, passed: false, finalAction: "NO_BET" as const, reasons: [...p.criticReport.reasons, "超出单日推荐数量上限。"]}});
}
export const getProbabilityByAction = (p: ThreeWayProbability, action: RecommendationType) => action === "HOME" ? p.home : action === "DRAW" ? p.draw : action === "AWAY" ? p.away : 0;
