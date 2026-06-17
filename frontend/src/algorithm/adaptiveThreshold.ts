import type {RiskLevel} from "../types";

export function calculateAdaptiveEvThreshold(matchContext:{outcome?:"HOME"|"DRAW"|"AWAY";odds?:number;leagueSample?:RiskLevel}={},riskContext:{modelDisagreement?:RiskLevel;pureModelReliability?:RiskLevel;lineupRisk?:RiskLevel;fatigueRisk?:RiskLevel}={},marketContext:{externalMarketQuality?:"HIGH"|"MEDIUM"|"LOW"|"UNAVAILABLE";clvHistory?:"POSITIVE"|"NEGATIVE"}={}) {
  let threshold=.03;
  if(marketContext.externalMarketQuality==="HIGH")threshold-=.005;
  else if(marketContext.externalMarketQuality==="LOW")threshold+=.015;
  else if(marketContext.externalMarketQuality==="UNAVAILABLE")threshold+=.025;
  if(riskContext.modelDisagreement==="MEDIUM")threshold+=.010; else if(riskContext.modelDisagreement==="HIGH")threshold+=.025;
  if(riskContext.pureModelReliability==="LOW")threshold+=.015;
  if(riskContext.lineupRisk==="HIGH")threshold+=.015;
  if(riskContext.fatigueRisk==="HIGH")threshold+=.010;
  if(matchContext.outcome==="DRAW")threshold+=.010;
  const odds=matchContext.odds??2;if(odds<1.3)threshold+=.015;if(odds>5)threshold+=.020;
  if(matchContext.leagueSample==="LOW")threshold+=.015;
  if(marketContext.clvHistory==="POSITIVE")threshold-=.005; else if(marketContext.clvHistory==="NEGATIVE")threshold+=.015;
  return Math.max(.02,Math.min(.10,threshold));
}
