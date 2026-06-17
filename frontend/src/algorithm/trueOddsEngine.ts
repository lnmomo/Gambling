import type {EdgeQualityOutput, MatchPrediction, OfficialMatch, ProbabilityUncertainty, ThreeWayProbability, TrueOddsEstimate} from "../types";
import {normalizeProbability} from "./ensembleModel";
import {calculateMultiDevigProbabilities} from "./multiDevig";
import {calculateAdaptiveEvThreshold} from "./adaptiveThreshold";
import {calculateEdgeQuality, trueFairOdds} from "./edgeQuality";

const keys=["home","draw","away"] as const;
const mean=(values:number[])=>values.length?values.reduce((a,b)=>a+b,0)/values.length:0;
function calibrateDraw(base:ThreeWayProbability,prediction:MatchPrediction){
  let delta=0,total=prediction.lambdaHome+prediction.lambdaAway,diff=Math.abs(prediction.lambdaHome-prediction.lambdaAway);
  if(total<2.2)delta+=.012;else if(total>3)delta-=.012;if(diff<.25)delta+=.01;
  if((prediction.pureModelBreakdown?.leagueParameters.goalVariance??1)>1.4)delta-=.01;
  const sample=Math.min(prediction.diagnostics.homeMatchCount,prediction.diagnostics.awayMatchCount,prediction.diagnostics.leagueMatchCount);
  const shrink=sample>=100?1:sample>=30?.5:.25;delta=Math.max(-.025,Math.min(.025,delta*shrink));
  const draw=Math.max(.05,Math.min(.45,base.draw+delta)),remain=1-draw,ha=base.home+base.away;
  return{probability:normalizeProbability({home:remain*base.home/ha,draw,away:remain*base.away/ha}),details:{applied:Math.abs(delta)>1e-9,drawDelta:delta,sampleCount:sample}};
}
function uncertainty(meanProbability:ThreeWayProbability,sources:ThreeWayProbability[],methodSpread:ProbabilityUncertainty["methodSpread"],prediction:MatchPrediction):ProbabilityUncertainty{
  const sample=Math.min(prediction.diagnostics.homeMatchCount,prediction.diagnostics.awayMatchCount),sampleReliability=Math.max(0,Math.min(1,sample/20)),disagreement={home:0,draw:0,away:0};
  keys.forEach(key=>{const values=sources.map(source=>source[key]);disagreement[key]=Math.max(...values)-Math.min(...values)});
  const risk=(prediction.pureModelBreakdown?.lineupImpact.riskLevel==="HIGH"?.015:0)+(prediction.pureModelBreakdown?.fatigue.riskLevel==="HIGH"?.01:0),std={home:0,draw:0,away:0},lower={home:0,draw:0,away:0},upper={home:0,draw:0,away:0},confidence={home:0,draw:0,away:0};
  keys.forEach(key=>{std[key]=Math.max(.015,Math.min(.12,(methodSpread[key]??0)*.45+disagreement[key]*.55+(1-sampleReliability)*.025+risk));lower[key]=Math.max(0,meanProbability[key]-std[key]);upper[key]=Math.min(1,meanProbability[key]+std[key]);confidence[key]=Math.max(0,Math.min(1,1-std[key]/.12))});
  const overallUncertainty=Math.max(std.home,std.draw,std.away)/.12;
  return{mean:meanProbability,lower,upper,std,confidence,methodSpread,modelDisagreement:disagreement,sampleReliability,overallUncertainty,warnings:overallUncertainty>.75?["probability uncertainty is high"]:[]};
}
export function calculateTrueOddsEstimate(match:Pick<OfficialMatch,"id"|"officialMatchId"|"league"|"officialSp">,prediction:MatchPrediction,options:{mode?:"SHADOW"|"FILTER_ONLY"|"ADJUST_PROBABILITY"}={}):TrueOddsEstimate{
  void options;
  const marketMultiDevig=calculateMultiDevigProbabilities(match.officialSp,{source:"official_sp"}),externalOdds=prediction.normalizedBookmakers[0]?.rawOdds,externalMultiDevig=externalOdds?calculateMultiDevigProbabilities(externalOdds,{source:"external_market"}):undefined;
  const baseProbability=normalizeProbability(prediction.finalProbability),draw=calibrateDraw(baseProbability,prediction),biasCorrectedProbability=draw.probability;
  const probUncertainty=uncertainty(biasCorrectedProbability,[prediction.marketProbability,prediction.externalMarketProbability,prediction.pureModelProbability,prediction.finalProbability],marketMultiDevig.methodSpread,prediction);
  const edgeQualityByOutcome={} as TrueOddsEstimate["edgeQualityByOutcome"];
  const sampleSize=Math.min(prediction.diagnostics.homeMatchCount,prediction.diagnostics.awayMatchCount);
  (["HOME","DRAW","AWAY"] as const).forEach(outcome=>{const key=outcome==="HOME"?"home":outcome==="DRAW"?"draw":"away",threshold=calculateAdaptiveEvThreshold({outcome,odds:match.officialSp[key],leagueSample:prediction.diagnostics.leagueReliability},{modelDisagreement:prediction.modelDisagreement.level,pureModelReliability:prediction.pureModelBreakdown?.reliability,lineupRisk:prediction.pureModelBreakdown?.lineupImpact.riskLevel,fatigueRisk:prediction.pureModelBreakdown?.fatigue.riskLevel},{externalMarketQuality:prediction.externalMarketQuality.qualityLevel});edgeQualityByOutcome[outcome]=calculateEdgeQuality(outcome,match.officialSp[key],biasCorrectedProbability,probUncertainty,{adaptiveThreshold:threshold,methodAgreementScore:marketMultiDevig.methodAgreementScore,externalMarketQuality:prediction.externalMarketQuality.qualityLevel,modelDisagreement:prediction.modelDisagreement.level,pureModelReliability:prediction.pureModelBreakdown?.reliability,lineupRisk:prediction.pureModelBreakdown?.lineupImpact.riskLevel,fatigueRisk:prediction.pureModelBreakdown?.fatigue.riskLevel,sampleSize:sampleSize<10?"LOW":"MEDIUM",drawCalibratorSupport:outcome!=="DRAW"||draw.details.applied})});
  const passed=Object.values(edgeQualityByOutcome).filter(row=>row.passesTrueOddsFilter),selectedEdge:EdgeQualityOutput=passed.sort((a,b)=>b.edgeQualityScore-a.edgeQualityScore||b.expectedEv-a.expectedEv)[0]??{outcome:"NO_BET",officialSp:0,breakEvenProbability:0,estimatedProbability:0,lowerBoundProbability:0,upperBoundProbability:0,expectedEv:0,lowerBoundEv:0,upperBoundEv:0,expectedClosingEdge:null,clvWinProbability:null,edgeQualityScore:0,edgeQualityLevel:"NO_EDGE",edgeNoiseRisk:"HIGH",adaptiveThreshold:Math.min(...Object.values(edgeQualityByOutcome).map(row=>row.adaptiveThreshold)),passesTrueOddsFilter:false,reasons:["没有 outcome 通过 true odds filter"],warnings:[]};
  return{matchId:match.id,officialMatchId:match.officialMatchId,createdAt:new Date().toISOString(),marketMultiDevig,externalMultiDevig,baseProbability,biasCorrectedProbability,uncertainty:probUncertainty,trueProbabilityEstimate:biasCorrectedProbability,trueFairOdds:trueFairOdds(biasCorrectedProbability),edgeQualityByOutcome,selectedEdge,drawCalibration:draw.details,warnings:[...probUncertainty.warnings]};
}
