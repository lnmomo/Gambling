import type {MatchPrediction, RiskLevel, StackingFeatureVector, ThreeWayProbability} from "../types";

export const DEFAULT_STACKING_FEATURE_NAMES = [
  "marketHomeProb", "marketDrawProb", "marketAwayProb", "externalHomeProb", "externalDrawProb", "externalAwayProb",
  "pureHomeProb", "pureDrawProb", "pureAwayProb", "dixonHomeProb", "dixonDrawProb", "dixonAwayProb",
  "eloHomeProb", "eloDrawProb", "eloAwayProb", "glickoHomeProb", "glickoDrawProb", "glickoAwayProb",
  "xgHomeProb", "xgDrawProb", "xgAwayProb", "externalMarketQualityScore", "externalMarketQualityLevelEncoded",
  "pureModelReliabilityEncoded", "leagueReliabilityEncoded", "lineupRiskEncoded", "fatigueRiskEncoded",
  "homeStrengthReliability", "awayStrengthReliability", "xgUsed", "fittedRho", "lambdaHome", "lambdaAway",
  "lambdaDiff", "lambdaTotal", "maxMarketPureDeviation", "maxExternalOfficialDeviation", "maxSubModelDeviation",
  "isCup", "isFriendly", "isInternational", "neutralVenue",
] as const;

type MatchLike = {id: string; officialMatchId: string; kickoffTime: string; league: string; context?: {isCupOrFriendly?: boolean}; neutralVenue?: boolean};
type Intermediate = Partial<MatchPrediction> & {actualResult?: "HOME" | "DRAW" | "AWAY"};
const neutral = (): ThreeWayProbability => ({home: 1 / 3, draw: 1 / 3, away: 1 / 3});
const triple = (value?: ThreeWayProbability) => value && Object.values(value).every(Number.isFinite) ? value : neutral();
const risk = (value?: RiskLevel) => value === "HIGH" ? 1 : value === "LOW" ? 0 : .5;
const reliability = (value?: "HIGH" | "MEDIUM" | "LOW") => value === "HIGH" ? 1 : value === "MEDIUM" ? .5 : 0;
const quality = (value?: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE") => value === "HIGH" ? 1 : value === "MEDIUM" ? .66 : value === "LOW" ? .33 : 0;
const maxDeviation = (items: ThreeWayProbability[]) => {
  let max = 0;
  for (const key of ["home", "draw", "away"] as const) for (let i = 0; i < items.length; i += 1) for (let j = i + 1; j < items.length; j += 1) max = Math.max(max, Math.abs(items[i][key] - items[j][key]));
  return max;
};

export function sanitizeFeatureVector(vector: StackingFeatureVector): StackingFeatureVector {
  const result = {...vector} as StackingFeatureVector;
  for (const [name, raw] of Object.entries(result)) {
    if (typeof raw !== "number") continue;
    const fallback = /Prob$/.test(name) ? 1 / 3 : 0;
    let value = Number.isFinite(raw) ? raw : fallback;
    if (/Prob$|Encoded$|Reliability$|^xgUsed$|^is|neutralVenue/.test(name)) value = Math.min(1, Math.max(0, value));
    if (/Odds|officialSp/i.test(name)) value = Math.min(100, Math.max(0, value));
    (result as unknown as Record<string, unknown>)[name] = value;
  }
  return result;
}

export function extractFeatureArray(vector: StackingFeatureVector, featureNames: string[]): number[] {
  const safe = sanitizeFeatureVector(vector) as unknown as Record<string, unknown>;
  return featureNames.map(name => typeof safe[name] === "number" && Number.isFinite(safe[name]) ? Number(safe[name]) : 0);
}

export function buildStackingFeatureVector(match: MatchLike, prediction: Intermediate, options: {includeLabel?: boolean} = {}): StackingFeatureVector {
  const market = triple(prediction.marketProbability), external = triple(prediction.externalMarketProbability), pure = triple(prediction.pureModelProbability);
  const breakdown = prediction.pureModelBreakdown, dixon = triple(breakdown?.dixonColesProbability ?? prediction.dixonColesProbability), elo = triple(breakdown?.eloProbability ?? prediction.eloProbability);
  const glicko = triple(breakdown?.glickoLikeProbability), xg = triple(breakdown?.xgPoissonProbability), sp = prediction.officialSp ?? {home: 0, draw: 0, away: 0};
  const marketOdds = prediction.marketFairOdds ?? {home: 0, draw: 0, away: 0}, externalOdds = prediction.externalMarketFairOdds ?? {home: 0, draw: 0, away: 0}, pureOdds = prediction.pureModelFairOdds ?? {home: 0, draw: 0, away: 0};
  const pureEdge = prediction.pureModelEdge ?? {home: 0, draw: 0, away: 0}, finalEdge = prediction.finalEdge ?? {home: 0, draw: 0, away: 0};
  const league = match.league.toLowerCase(), isFriendly = /friendly|友谊/.test(league) ? 1 : 0, isInternational = /international|world|国家|世界杯|欧国联/.test(league) ? 1 : 0;
  return sanitizeFeatureVector({
    matchId: match.id, officialMatchId: match.officialMatchId, kickoffTime: match.kickoffTime, league: match.league,
    marketHomeProb: market.home, marketDrawProb: market.draw, marketAwayProb: market.away,
    externalHomeProb: external.home, externalDrawProb: external.draw, externalAwayProb: external.away,
    pureHomeProb: pure.home, pureDrawProb: pure.draw, pureAwayProb: pure.away,
    dixonHomeProb: dixon.home, dixonDrawProb: dixon.draw, dixonAwayProb: dixon.away,
    eloHomeProb: elo.home, eloDrawProb: elo.draw, eloAwayProb: elo.away,
    glickoHomeProb: glicko.home, glickoDrawProb: glicko.draw, glickoAwayProb: glicko.away,
    xgHomeProb: xg.home, xgDrawProb: xg.draw, xgAwayProb: xg.away,
    officialSpHome: sp.home, officialSpDraw: sp.draw, officialSpAway: sp.away,
    marketFairOddsHome: marketOdds.home, marketFairOddsDraw: marketOdds.draw, marketFairOddsAway: marketOdds.away,
    externalFairOddsHome: externalOdds.home, externalFairOddsDraw: externalOdds.draw, externalFairOddsAway: externalOdds.away,
    pureFairOddsHome: pureOdds.home, pureFairOddsDraw: pureOdds.draw, pureFairOddsAway: pureOdds.away,
    pureEdgeHome: pureEdge.home, pureEdgeDraw: pureEdge.draw, pureEdgeAway: pureEdge.away,
    finalEdgeHome: finalEdge.home, finalEdgeDraw: finalEdge.draw, finalEdgeAway: finalEdge.away,
    maxMarketPureDeviation: Math.max(Math.abs(market.home - pure.home), Math.abs(market.draw - pure.draw), Math.abs(market.away - pure.away)),
    maxExternalOfficialDeviation: prediction.externalMarketQuality?.officialMarketDeviation.maxDeviation ?? 0,
    maxSubModelDeviation: maxDeviation([dixon, elo, glicko, xg]), externalMarketQualityScore: prediction.externalMarketQuality?.qualityScore ?? 0,
    externalMarketQualityLevelEncoded: quality(prediction.externalMarketQuality?.qualityLevel), pureModelReliabilityEncoded: reliability(breakdown?.reliability),
    leagueReliabilityEncoded: reliability(breakdown?.leagueParameters.reliability), lineupRiskEncoded: risk(breakdown?.lineupImpact.riskLevel), fatigueRiskEncoded: risk(breakdown?.fatigue.riskLevel),
    homeStrengthReliability: breakdown?.homeStrength.overallReliability ?? 0, awayStrengthReliability: breakdown?.awayStrength.overallReliability ?? 0,
    xgUsed: breakdown?.xgPoissonProbability ? 1 : 0, fittedRho: breakdown?.leagueParameters.fittedRho ?? 0,
    lambdaHome: prediction.lambdaHome ?? breakdown?.lambdaHome ?? 0, lambdaAway: prediction.lambdaAway ?? breakdown?.lambdaAway ?? 0,
    lambdaDiff: (prediction.lambdaHome ?? breakdown?.lambdaHome ?? 0) - (prediction.lambdaAway ?? breakdown?.lambdaAway ?? 0),
    lambdaTotal: (prediction.lambdaHome ?? breakdown?.lambdaHome ?? 0) + (prediction.lambdaAway ?? breakdown?.lambdaAway ?? 0),
    isCup: match.context?.isCupOrFriendly && !isFriendly ? 1 : /cup|杯/.test(league) ? 1 : 0, isFriendly, isInternational, neutralVenue: match.neutralVenue ? 1 : 0,
    actualResult: options.includeLabel ? prediction.actualResult : undefined,
  });
}
