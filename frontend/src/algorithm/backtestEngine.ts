import type {BacktestInputMatch, BacktestRecord, BankrollTransaction, HistoricalMatch, MatchPrediction, RecommendationType, StackingModelCoefficients, WalkForwardBacktestResult} from "../types";
import {createDefaultBankrollConfig} from "./bankrollManager";
import {calculateDrawdownState} from "./drawdownControl";
import {calculatePortfolioExposure} from "./portfolioRisk";
import {calculateMatchPrediction} from "./probabilityEngine";
import {calculateBacktestMetrics, calculateBrierScore, calculateLogLoss} from "./backtestMetrics";
import {buildCalibrationTable} from "./calibrationAnalysis";
import {calculateClv} from "./clvAnalysis";
import {analyzePredictionErrors} from "./errorAnalysis";
import {assertNoFutureLeakage, getPastMatchesOnly, sortMatchesByTime} from "./timeSplit";

const key = (action: Exclude<RecommendationType, "NO_BET">) => action === "HOME" ? "home" : action === "DRAW" ? "draw" : "away";
export function runWalkForwardBacktest(inputMatches: BacktestInputMatch[], historicalMatches: HistoricalMatch[], options: {bankroll?: number; temperature?: number; includeNoBet?: boolean; startDate?: string; endDate?: string; useStacking?: boolean; stackingCoefficients?: StackingModelCoefficients} = {}): WalkForwardBacktestResult {
  const config = createDefaultBankrollConfig(); config.initialBankroll = options.bankroll ?? 10_000; config.currentBankroll = config.initialBankroll; config.maxStakeUnit = Math.max(config.baseUnit, config.currentBankroll * config.maxStakePerBetPct);
  const start = options.startDate ? Date.parse(options.startDate) : -Infinity, end = options.endDate ? Date.parse(options.endDate) : Infinity, transactions:BankrollTransaction[]=[], activePredictions:MatchPrediction[]=[];
  const records = sortMatchesByTime(inputMatches).filter(match => { const time = Date.parse(match.kickoffTime); return Number.isFinite(time) && time >= start && time <= end; }).map((match): BacktestRecord => {
    const pastMatches = getPastMatchesOnly(historicalMatches, match.kickoffTime), leakage = assertNoFutureLeakage(pastMatches, match.kickoffTime);
    if (!leakage.valid) throw new Error(leakage.warnings.join(" "));
    const bankrollBefore=config.currentBankroll;
    const portfolioExposureAtBet=calculatePortfolioExposure(activePredictions,config.currentBankroll,match.kickoffTime.slice(0,10)),drawdownState=calculateDrawdownState(transactions,config);
    const prediction = calculateMatchPrediction({...match, status: "NOT_STARTED", marketOdds: {home: 0, draw: 0, away: 0}, updatedAt: match.kickoffTime}, pastMatches, match.context ?? {}, config.currentBankroll, {temperature: options.temperature, useStacking: options.useStacking, stackingCoefficients: options.stackingCoefficients, attachStakeRecommendation:true, bankrollConfig:config, activePredictions, bankrollTransactions:transactions});
    const recommendation = prediction.recommendation, actualResult = match.result?.result, isBet = recommendation !== "NO_BET", selectedKey = isBet ? key(recommendation) : undefined;
    const selectedProbability = selectedKey ? prediction.finalProbability[selectedKey] : undefined, selectedOfficialSp = selectedKey ? match.officialSp[selectedKey] : undefined, selectedClosingSp = selectedKey ? match.closingSp?.[selectedKey] : undefined;
    const stake = isBet ? prediction.suggestedStake : 0, hit = isBet && actualResult ? recommendation === actualResult : null;
    const profit = hit === null ? 0 : hit ? stake * ((selectedOfficialSp ?? 1) - 1) : -stake, clv = selectedOfficialSp && selectedClosingSp ? calculateClv(selectedOfficialSp, selectedClosingSp) : undefined;
    config.currentBankroll=Math.max(0,config.currentBankroll+profit);
    if(isBet&&hit!==null)transactions.push({id:`bt-${transactions.length+1}`,bankrollId:config.bankrollId,matchId:match.id,officialMatchId:match.officialMatchId,type:hit?"BET_WON":"BET_LOST",amount:profit,bankrollBefore,bankrollAfter:config.currentBankroll,createdAt:match.kickoffTime});
    if(prediction.recommendation!=="NO_BET")activePredictions.push({...prediction,league:match.league,kickoffTime:match.kickoffTime} as MatchPrediction);
    const pure=prediction.pureModelBreakdown;return {matchId: match.id, officialMatchId: match.officialMatchId, league: match.league, homeTeam: match.homeTeam, awayTeam: match.awayTeam, kickoffTime: match.kickoffTime, prediction, actualResult, recommendation, selectedProbability, selectedOfficialSp, selectedClosingSp, ev: selectedKey ? prediction.ev[selectedKey] : undefined, stake, profit, hit, clv, clvPositive: clv === undefined ? null : clv > 0, brierScore: actualResult ? calculateBrierScore(prediction.finalProbability, actualResult) : 0, logLoss: actualResult ? calculateLogLoss(prediction.finalProbability, actualResult) : 0, riskLevel: prediction.riskLevel, externalMarketQualityLevel: prediction.externalMarketQuality.qualityLevel, modelDisagreementLevel: prediction.modelDisagreement.level,pureModelReliability:pure?.reliability,leagueReliability:pure?.leagueParameters.reliability,homeStrengthReliability:pure?.homeStrength.overallReliability,awayStrengthReliability:pure?.awayStrength.overallReliability,lineupRiskLevel:pure?.lineupImpact.riskLevel,fatigueRiskLevel:pure?.fatigue.riskLevel,xgUsed:Boolean(pure?.xgPoissonProbability),fittedRho:pure?.leagueParameters.fittedRho, probabilitySource:prediction.probabilitySource,modelVersion:prediction.modelVersion,stackingConfidence:prediction.stackingPrediction?.confidence,stackingFallbackUsed:prediction.stackingPrediction?.fallbackUsed,stackingTopFeatures:prediction.stackingPrediction?.topFeatures, pureModelEdge: selectedKey ? prediction.pureModelEdge[selectedKey] : undefined, finalEdge: selectedKey ? prediction.finalEdge[selectedKey] : undefined, noBetReason: prediction.criticReport.reasons, warnings: [...prediction.criticReport.warnings, ...prediction.diagnostics.warnings],bankrollBefore,bankrollAfter:config.currentBankroll,suggestedStake:prediction.stakeRecommendation?.finalStake??stake,stakePctOfBankroll:prediction.stakeRecommendation?.stakePctOfBankroll,stakeCappedBy:prediction.stakeRecommendation?.cappedBy,stakeStatus:prediction.stakeRecommendation?.status,drawdownState,portfolioExposureAtBet};
  }).filter(record => options.includeNoBet !== false || record.recommendation !== "NO_BET");
  const metrics = calculateBacktestMetrics(records), calibrationTable = buildCalibrationTable(records, {useSelectedOnly: true}), errorAnalysis = analyzePredictionErrors(records);
  return {records, metrics, calibrationTable, errorAnalysis};
}
