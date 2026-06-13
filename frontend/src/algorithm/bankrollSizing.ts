import type {ConfidenceLevel, RecommendationType, RiskLevel} from "../types";
export function calculateFractionalKelly(probability: number, odds: number, bankroll: number, confidence: ConfidenceLevel, riskLevel: RiskLevel, recommendation: RecommendationType): number {
  if (recommendation === "NO_BET" || odds <= 1 || bankroll <= 0) return 0;
  const kelly = (probability * odds - 1) / (odds - 1);
  if (kelly <= 0) return 0;
  const confidenceMultiplier = {A: 1, B: .7, C: .4, D: .2}[confidence];
  const riskMultiplier = {LOW: 1, MEDIUM: .6, HIGH: .3}[riskLevel];
  return Math.max(0, Math.min(bankroll * .01, bankroll * kelly * .25 * confidenceMultiplier * riskMultiplier));
}
