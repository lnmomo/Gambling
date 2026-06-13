import type {MatchContext, RiskLevel} from "../types";

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
export function calculateContextAdjustments(context: MatchContext) {
  let homeImpact = 0, awayImpact = 0;
  const events = context.newsEvents ?? [];
  for (const event of events) {
    const impact = clamp(event.impact, -0.08, 0.08) * clamp(event.confidence, 0, 1);
    if (event.team === "HOME") {
      if ((event.type === "INJURY" || event.type === "SUSPENSION") && (event.position === "DEF" || event.position === "GK")) awayImpact -= impact;
      else homeImpact += impact;
    } else if ((event.type === "INJURY" || event.type === "SUSPENSION") && (event.position === "DEF" || event.position === "GK")) homeImpact -= impact;
    else awayImpact += impact;
  }
  homeImpact = clamp(homeImpact, -0.15, 0.15);
  awayImpact = clamp(awayImpact, -0.15, 0.15);
  let weatherAdjustment = 1;
  if (context.weather?.condition === "RAIN") weatherAdjustment = 0.97;
  if (context.weather?.condition === "HEAVY_RAIN") weatherAdjustment = 0.92;
  if (context.weather?.condition === "SNOW") weatherAdjustment = 0.90;
  if (context.weather?.condition === "WINDY") weatherAdjustment = context.weather.windSpeed > 8 ? 0.94 : 0.97;
  if (context.weather?.pitchCondition === "POOR") weatherAdjustment *= 0.96;
  const fatigue = (rest?: number, opponentRest?: number, travel = 0) => {
    const diff = (rest ?? opponentRest ?? 3) - (opponentRest ?? rest ?? 3);
    let factor = diff <= -4 ? 0.93 : diff <= -2 ? 0.96 : 1;
    factor *= travel > 3000 ? 0.94 : travel > 1500 ? 0.97 : 1;
    return factor;
  };
  const fatigueAdjustmentHome = fatigue(context.homeRestDays, context.awayRestDays, context.homeTravelDistance);
  const fatigueAdjustmentAway = fatigue(context.awayRestDays, context.homeRestDays, context.awayTravelDistance);
  const lineupPenalty = context.lineupKnown === false ? 0.015 : 0;
  const extremeWeather = ["HEAVY_RAIN", "SNOW"].includes(context.weather?.condition ?? "");
  const coreAbsences = events.filter(event => ["INJURY", "SUSPENSION"].includes(event.type) && event.playerImportance === "CORE").length;
  const highUncertainty = events.some(event => Math.abs(event.impact) >= 0.06 && event.confidence < 0.5);
  let contextRiskLevel: RiskLevel = extremeWeather || coreAbsences >= 2 || highUncertainty ? "HIGH" : events.length || weatherAdjustment < 1 || context.lineupKnown === false ? "MEDIUM" : "LOW";
  if (context.riskLimitTriggered) contextRiskLevel = "HIGH";
  return {newsAdjustmentHome: 1 + homeImpact, newsAdjustmentAway: 1 + awayImpact, weatherAdjustment, fatigueAdjustmentHome, fatigueAdjustmentAway, lineupPenalty, contextRiskLevel, details: events.map(event => `${event.team} ${event.type}: ${(event.impact * event.confidence * 100).toFixed(1)}%`)};
}
