import type {EdgeQualityOutput, ProbabilityUncertainty, RiskLevel, ThreeWayOdds, ThreeWayProbability} from "../types";

const keyOf=(outcome:"HOME"|"DRAW"|"AWAY")=>outcome==="HOME"?"home":outcome==="DRAW"?"draw":"away";
export function calculateEdgeQuality(outcome:"HOME"|"DRAW"|"AWAY",officialSp:number,estimated:ThreeWayProbability,uncertainty:ProbabilityUncertainty,context:{adaptiveThreshold:number;methodAgreementScore?:number;externalMarketQuality?:string;modelDisagreement?:RiskLevel;pureModelReliability?:RiskLevel;lineupRisk?:RiskLevel;fatigueRisk?:RiskLevel;sampleSize?:RiskLevel;drawCalibratorSupport?:boolean;criticBlocked?:boolean;expectedClosingEdge?:number|null;clvWinProbability?:number|null}):EdgeQualityOutput{
  const key=keyOf(outcome),p=estimated[key],lower=uncertainty.lower[key],upper=uncertainty.upper[key],expectedEv=p*officialSp-1,lowerBoundEv=lower*officialSp-1,upperBoundEv=upper*officialSp-1,reasons:string[]=[],warnings:string[]=[];
  let score=50;if(expectedEv>context.adaptiveThreshold+.03)score+=15;else if(expectedEv>context.adaptiveThreshold)score+=8;
  if(lowerBoundEv>0)score+=20;else{score-=25;reasons.push("lowerBoundEV <= 0")}
  if((context.clvWinProbability??.5)>.55)score+=10;
  if(context.expectedClosingEdge!==undefined&&context.expectedClosingEdge!==null)score+=context.expectedClosingEdge>0?10:-20;
  score+=10*(context.methodAgreementScore??0);
  if(context.externalMarketQuality==="HIGH")score+=10;
  if(context.modelDisagreement==="HIGH"){score-=20;reasons.push("模型分歧过高")}
  if(context.pureModelReliability==="LOW")score-=15;
  if(context.lineupRisk==="HIGH")score-=10;if(context.fatigueRisk==="HIGH")score-=10;
  if(outcome==="DRAW"&&!context.drawCalibratorSupport)score-=8;
  if(officialSp>5||officialSp<1.3)score-=10;
  if(context.sampleSize==="LOW")score-=15;
  score=Math.max(0,Math.min(100,score));
  const edgeQualityLevel=score>=75?"HIGH":score>=55?"MEDIUM":score>=35?"LOW":"NO_EDGE";
  const edgeNoiseRisk:RiskLevel=uncertainty.overallUncertainty>=.75||context.modelDisagreement==="HIGH"?"HIGH":uncertainty.overallUncertainty>=.5?"MEDIUM":"LOW";
  if(expectedEv<=context.adaptiveThreshold)reasons.push("expected EV 未超过 adaptive threshold");
  if(edgeNoiseRisk==="HIGH")reasons.push("edge 噪声风险过高");
  const passesTrueOddsFilter=expectedEv>context.adaptiveThreshold&&lowerBoundEv>0&&(edgeQualityLevel==="HIGH"||edgeQualityLevel==="MEDIUM")&&edgeNoiseRisk!=="HIGH"&&!context.criticBlocked;
  return{outcome,officialSp,breakEvenProbability:1/officialSp,estimatedProbability:p,lowerBoundProbability:lower,upperBoundProbability:upper,expectedEv,lowerBoundEv,upperBoundEv,expectedClosingEdge:context.expectedClosingEdge,clvWinProbability:context.clvWinProbability,edgeQualityScore:score,edgeQualityLevel,edgeNoiseRisk,adaptiveThreshold:context.adaptiveThreshold,passesTrueOddsFilter,reasons,warnings};
}
export const trueFairOdds=(p:ThreeWayProbability):ThreeWayOdds=>({home:1/Math.max(p.home,1e-12),draw:1/Math.max(p.draw,1e-12),away:1/Math.max(p.away,1e-12)});
