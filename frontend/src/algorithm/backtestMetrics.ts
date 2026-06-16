import type {BacktestMetrics, BacktestRecord, ThreeWayProbability} from "../types";
import {buildCalibrationTable, calculateExpectedCalibrationError} from "./calibrationAnalysis";

const mean = (values: number[]) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
const median = (values:number[])=>{if(!values.length)return 0;const sorted=[...values].sort((a,b)=>a-b),mid=Math.floor(sorted.length/2);return sorted.length%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2};
const std = (values:number[])=>{const avg=mean(values);return values.length?Math.sqrt(mean(values.map(value=>(value-avg)**2))):0};
export function calculateBrierScore(probability: ThreeWayProbability, actualResult: "HOME" | "DRAW" | "AWAY") {
  const actual = {HOME: [1, 0, 0], DRAW: [0, 1, 0], AWAY: [0, 0, 1]}[actualResult];
  return ([probability.home, probability.draw, probability.away].reduce((sum, value, index) => sum + (value - actual[index]) ** 2, 0)) / 3;
}
export function calculateLogLoss(probability: ThreeWayProbability, actualResult: "HOME" | "DRAW" | "AWAY") {
  const value = actualResult === "HOME" ? probability.home : actualResult === "DRAW" ? probability.draw : probability.away;
  return -Math.log(Math.min(1 - 1e-15, Math.max(1e-15, value)));
}
export function calculateMaxDrawdown(records: BacktestRecord[]) {
  let equity = 0, peak = 0, maxDrawdown = 0;
  for (const record of [...records].sort((a, b) => Date.parse(a.kickoffTime) - Date.parse(b.kickoffTime))) { equity += record.profit; peak = Math.max(peak, equity); maxDrawdown = Math.max(maxDrawdown, peak - equity); }
  return maxDrawdown;
}
export function calculateBacktestMetrics(records: BacktestRecord[]): BacktestMetrics {
  const bets = records.filter(record => record.recommendation !== "NO_BET" && record.hit !== null), settled = records.filter(record => record.actualResult), clvRows = bets.filter(record => Number.isFinite(record.clv));
  const totalStake = bets.reduce((sum, record) => sum + record.stake, 0), totalProfit = bets.reduce((sum, record) => sum + record.profit, 0), hitCount = bets.filter(record => record.hit).length;
  const calibrationTable = buildCalibrationTable(records, {useSelectedOnly: true});
  let losing=0,longestLosingStreak=0;for(const record of bets){if(record.hit===false){losing++;longestLosingStreak=Math.max(longestLosingStreak,losing)}else if(record.hit)losing=0}
  const stakes=bets.map(record=>record.stake),initial=records.find(record=>record.bankrollBefore!==undefined)?.bankrollBefore??0,final=[...records].reverse().find(record=>record.bankrollAfter!==undefined)?.bankrollAfter??initial,totalDaily=new Map<string,number>();for(const record of records){const day=record.kickoffTime.slice(0,10);totalDaily.set(day,(totalDaily.get(day)??0)+(record.stake||0))}
  const dailyExposure=[...totalDaily.values()].map(value=>initial?value/initial:0);
  return {totalMatches: records.length, totalBets: bets.length, noBetCount: records.filter(record => record.recommendation === "NO_BET").length, noBetRatio: records.length ? records.filter(record => record.recommendation === "NO_BET").length / records.length : 0, hitCount, hitRate: bets.length ? hitCount / bets.length : 0, totalStake, totalProfit, roi: totalStake ? totalProfit / totalStake : 0, maxDrawdown: calculateMaxDrawdown(records), averageEv: mean(bets.flatMap(record => record.ev === undefined ? [] : [record.ev])), averageClv: mean(clvRows.map(record => record.clv!)), positiveClvRate: clvRows.length ? clvRows.filter(record => record.clv! > 0).length / clvRows.length : 0, brierScore: mean(settled.map(record => record.brierScore)), logLoss: mean(settled.map(record => record.logLoss)), averagePredictedProbability: mean(bets.flatMap(record => record.selectedProbability === undefined ? [] : [record.selectedProbability])), averageActualHitRate: bets.length ? hitCount / bets.length : 0, calibrationError: calculateExpectedCalibrationError(calibrationTable),finalBankroll:final,bankrollGrowth:final-initial,bankrollGrowthPct:initial?(final-initial)/initial:0,averageStake:mean(stakes),medianStake:median(stakes),maxStake:Math.max(0,...stakes),stakeVolatility:std(stakes),longestLosingStreak,riskAdjustedRoi:std(stakes)?(totalStake?totalProfit/totalStake:0)/std(stakes):0,averageDailyExposure:mean(dailyExposure),maxDailyExposure:Math.max(0,...dailyExposure),averageLeagueConcentration:0,stakeBlockedCount:records.filter(record=>record.stakeStatus==="STAKE_BLOCKED").length,stakeReducedCount:records.filter(record=>record.stakeStatus==="STAKE_REDUCED").length};
}
