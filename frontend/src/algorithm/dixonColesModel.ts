import type {ScoreProbability, ThreeWayProbability} from "../types";
import type {LeagueParameters} from "../types";
import {AlgorithmConfig} from "./config";

export function poissonPmf(k: number, lambda: number): number {
  let factorial = 1;
  for (let i = 2; i <= k; i += 1) factorial *= i;
  return Math.exp(-lambda) * lambda ** k / factorial;
}

export function dixonColesAdjustment(homeGoals: number, awayGoals: number, lambdaHome: number, lambdaAway: number, rho = -0.10): number {
  if (homeGoals === 0 && awayGoals === 0) return 1 - lambdaHome * lambdaAway * rho;
  if (homeGoals === 0 && awayGoals === 1) return 1 + lambdaHome * rho;
  if (homeGoals === 1 && awayGoals === 0) return 1 + lambdaAway * rho;
  if (homeGoals === 1 && awayGoals === 1) return 1 - rho;
  return 1;
}

export function calculateDixonColesScoreMatrix(lambdaHome: number, lambdaAway: number, maxGoals = 10, rho = -0.10): ScoreProbability[] {
  const rows: ScoreProbability[] = [];
  for (let homeGoals = 0; homeGoals <= maxGoals; homeGoals += 1) {
    for (let awayGoals = 0; awayGoals <= maxGoals; awayGoals += 1) {
      rows.push({homeGoals, awayGoals, probability: Math.max(0, poissonPmf(homeGoals, lambdaHome) * poissonPmf(awayGoals, lambdaAway) * dixonColesAdjustment(homeGoals, awayGoals, lambdaHome, lambdaAway, rho))});
    }
  }
  const total = rows.reduce((sum, row) => sum + row.probability, 0) || 1;
  return rows.map(row => ({...row, probability: row.probability / total}));
}

export function calculateDixonColes1X2(lambdaHome: number, lambdaAway: number, maxGoals = 10, rho = -0.10): {probability: ThreeWayProbability; scoreMatrix: ScoreProbability[]; topScores: ScoreProbability[]} {
  const scoreMatrix = calculateDixonColesScoreMatrix(lambdaHome, lambdaAway, maxGoals, rho);
  const probability = scoreMatrix.reduce((sum, row) => {
    sum[row.homeGoals > row.awayGoals ? "home" : row.homeGoals === row.awayGoals ? "draw" : "away"] += row.probability;
    return sum;
  }, {home: 0, draw: 0, away: 0});
  return {probability, scoreMatrix, topScores: [...scoreMatrix].sort((a, b) => b.probability - a.probability).slice(0, 10)};
}
export const estimateRhoByLeague = (parameters: LeagueParameters) => Math.min(AlgorithmConfig.dixonColes.maxRho, Math.max(AlgorithmConfig.dixonColes.minRho, parameters.drawRate >= .30 ? -.13 : parameters.drawRate <= .22 ? -.06 : -.10));
export const validateScoreMatrix = (matrix: ScoreProbability[]) => ({valid: matrix.length > 0 && matrix.every(row => Number.isFinite(row.probability) && row.probability >= 0) && Math.abs(matrix.reduce((sum, row) => sum + row.probability, 0) - 1) < .001, errors: matrix.length ? [] : ["比分矩阵为空。"]});
