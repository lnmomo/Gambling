export type MatchStatus = "NOT_STARTED" | "LIVE" | "FINISHED" | "CANCELLED" | "POSTPONED" | "CLOSED";
export type RecommendationType = "HOME" | "DRAW" | "AWAY" | "NO_BET";
export type BetOption = RecommendationType;
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";
export type ConfidenceLevel = "A" | "B" | "C" | "D";
export type ConfidenceGrade = ConfidenceLevel | "NO_BET";
export type AgentState = "RUNNING" | "DELAYED" | "WARNING";
export type RecommendationDecision = RecommendationType;
export type OddsSnapshotType = "OPENING" | "REGULAR" | "PRE_MATCH" | "CLOSING" | "POSTPONED" | "CANCELLED";
export type RecommendationLifecycleStatus = "ACTIVE" | "STALE" | "DOWNGRADED" | "WITHDRAWN" | "CLOSED" | "NO_BET";
export type ModelRole = "CHAMPION" | "CHALLENGER" | "ARCHIVED";

export interface ThreeWayProbability { home: number; draw: number; away: number }
export type ProbabilityTriple = ThreeWayProbability;
export type ModelProbability = ThreeWayProbability;
export interface OfficialSp extends ThreeWayProbability {}
export type ThreeWayOdds = OfficialSp;
export type ThreeWayEdge = ThreeWayProbability;
export interface ExternalBookmakerOdds { bookmaker: string; bookmakerKey?: string; market: "H2H" | "1X2"; odds: ThreeWayOdds; lastUpdate: string; source?: string; weight?: number }
export interface NormalizedBookmakerProbability { bookmaker: string; bookmakerKey?: string; rawOdds: ThreeWayOdds; rawImpliedProbability: ThreeWayProbability; normalizedProbability: ThreeWayProbability; overround: number; weight: number; included: boolean; exclusionReason?: string; lastUpdate: string }
export interface ExternalMarketDeviation { homeDeviation: number; drawDeviation: number; awayDeviation: number; maxDeviation: number }
export interface ExternalMarketQuality { available: boolean; bookmakerCount: number; includedBookmakerCount: number; excludedBookmakerCount: number; averageOverround: number; maxBookmakerDeviation: number; officialMarketDeviation: ExternalMarketDeviation; staleCount: number; qualityScore: number; qualityLevel: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE"; warnings: string[] }
export interface ExternalMarketConsensus { probability: ThreeWayProbability; fairOdds: ThreeWayOdds; normalizedBookmakers: NormalizedBookmakerProbability[]; quality: ExternalMarketQuality; warnings: string[]; fallbackUsed: boolean; fallbackReason?: string }
export interface OfficialSpSnapshot { id:string; matchId:string; officialMatchId:string; capturedAt:string; snapshotType:OddsSnapshotType; sp:ThreeWayOdds; marketProbability:ThreeWayProbability; marketFairOdds:ThreeWayOdds; source:"CHINA_LOTTERY_OFFICIAL"; rawPayloadHash?:string; isValid:boolean; warnings:string[] }
export interface ExternalOddsSnapshot { id:string; matchId:string; officialMatchId:string; capturedAt:string; snapshotType:OddsSnapshotType; bookmakerOdds:ExternalBookmakerOdds[]; externalMarketProbability:ThreeWayProbability; externalMarketFairOdds:ThreeWayOdds; externalMarketQuality:ExternalMarketQuality; normalizedBookmakers:NormalizedBookmakerProbability[]; source:"THE_ODDS_API"; rawPayloadHash?:string; isValid:boolean; warnings:string[] }
export interface MarketMovementSignal { matchId:string; officialMatchId:string; detectedAt:string; type:"OFFICIAL_SP_DROP"|"OFFICIAL_SP_RISE"|"EXTERNAL_ODDS_DROP"|"EXTERNAL_ODDS_RISE"|"OFFICIAL_EXTERNAL_DIVERGENCE"|"MARKET_CONSENSUS_SHIFT"|"LATE_STEAM_MOVE"|"DATA_STALE"|"SUSPICIOUS_SPIKE"; outcome?:"HOME"|"DRAW"|"AWAY"; severity:RiskLevel; beforeProbability?:number; afterProbability?:number; probabilityDelta?:number; beforeOdds?:number; afterOdds?:number; oddsDelta?:number; description:string; recommendedAction:"KEEP"|"RECALCULATE"|"RAISE_THRESHOLD"|"WITHDRAW_RECOMMENDATION"|"NO_BET"; warnings:string[] }
export interface LiveRecalculationTrigger { id:string; matchId:string; officialMatchId:string; triggeredAt:string; type:"OFFICIAL_SP_CHANGED"|"EXTERNAL_MARKET_CHANGED"|"NEWS_CHANGED"|"LINEUP_CHANGED"|"WEATHER_CHANGED"|"MATCH_STATUS_CHANGED"|"SCHEDULED_REFRESH"|"MANUAL_REFRESH"; severity:RiskLevel; description:string; previousSnapshotId?:string; newSnapshotId?:string }
export interface RecommendationLifecycleEvent { id:string; matchId:string; officialMatchId:string; occurredAt:string; previousStatus?:RecommendationLifecycleStatus; newStatus:RecommendationLifecycleStatus; previousRecommendation?:RecommendationDecision; newRecommendation?:RecommendationDecision; reason:string; triggerType?:LiveRecalculationTrigger["type"]; previousEv?:number; newEv?:number; previousFinalProbability?:number; newFinalProbability?:number; auditLogId?:string }
export interface LiveRecalculationResult { id:string; matchId:string; officialMatchId:string; recalculatedAt:string; trigger:LiveRecalculationTrigger; previousPrediction?:MatchPrediction; newPrediction:MatchPrediction; probabilityDelta:{home:number;draw:number;away:number;maxDelta:number}; evDelta:{home:number;draw:number;away:number;maxDelta:number}; recommendationChanged:boolean; previousRecommendation?:RecommendationDecision; newRecommendation:RecommendationDecision; lifecycleStatus:RecommendationLifecycleStatus; warnings:string[] }
export interface ModelGovernanceRecord { modelId:string; modelName:string; modelType:"RULE_BASED_ENSEMBLE"|"STACKING_MODEL"|"ENHANCED_PURE_MODEL"|"EXTERNAL_MARKET_MODEL"; version:string; role:ModelRole; createdAt:string; activatedAt?:string; archivedAt?:string; trainingMatchCount?:number; validationMatchCount?:number; testMatchCount?:number; metrics:{logLoss:number;brierScore:number;calibrationError:number;roi?:number;averageClv?:number;positiveClvRate?:number}; baselineModelId?:string; promotionStatus:"NOT_EVALUATED"|"CANDIDATE"|"APPROVED"|"REJECTED"|"PROMOTED"|"ROLLED_BACK"; promotionReason?:string; warnings:string[] }
export interface ModelPromotionDecision { challengerModelId:string; championModelId:string; allowed:boolean; decision:"PROMOTE"|"KEEP_CHAMPION"|"NEED_MORE_DATA"|"REJECT_CHALLENGER"; reasons:string[]; requiredConditions:Array<{name:string;passed:boolean;value:number|string;threshold:number|string}> }
export interface AuditLogEntry { id:string; createdAt:string; entityType:"MATCH"|"PREDICTION"|"RECOMMENDATION"|"ODDS_SNAPSHOT"|"MODEL"|"SYSTEM"; entityId:string; action:"SNAPSHOT_CREATED"|"PREDICTION_RECALCULATED"|"RECOMMENDATION_CREATED"|"RECOMMENDATION_UPDATED"|"RECOMMENDATION_WITHDRAWN"|"MODEL_EVALUATED"|"MODEL_PROMOTION_CHECKED"|"WARNING_RAISED"|"ERROR_HANDLED"|"STAKE_CALCULATED"|"STAKE_REDUCED"|"STAKE_BLOCKED"|"BANKROLL_UPDATED"|"EXPOSURE_LIMIT_TRIGGERED"|"DRAWDOWN_MODE_CHANGED"|"CORRELATION_WARNING_RAISED"; summary:string; before?:unknown; after?:unknown; trigger?:LiveRecalculationTrigger; severity:"INFO"|"WARNING"|"ERROR"; actor:"SYSTEM"|"USER"|"SCHEDULER" }
export interface BankrollConfig { bankrollId:string; name:string; initialBankroll:number; currentBankroll:number; baseUnit:number; currency?:string; stakingMode:"FLAT_UNIT"|"FIXED_PERCENT"|"FRACTIONAL_KELLY"|"RISK_ADJUSTED_KELLY"; kellyFraction:number; maxStakePerBetPct:number; maxDailyExposurePct:number; maxLeagueExposurePct:number; maxSingleOutcomeTypeExposurePct:number; minStakeUnit:number; maxStakeUnit:number; drawdownControlEnabled:boolean; correlationControlEnabled:boolean; createdAt:string; updatedAt:string }
export interface KellyStakeOutput { probability:number; odds:number; edge:number; fullKellyFraction:number; fractionalKellyFraction:number; rawStake:number; cappedStake:number; positiveKelly:boolean; warnings:string[] }
export interface StakeAdjustmentFactor { name:string; factor:number; reason:string }
export interface StakeRecommendation { matchId:string; officialMatchId:string; recommendation:RecommendationType; finalProbability:number; officialSp:number; ev:number; bankroll:number; baseUnit:number; kelly:KellyStakeOutput; rawStake:number; adjustedStake:number; finalStake:number; stakePctOfBankroll:number; stakeUnits:number; riskLevel:RiskLevel; confidenceLevel:"LOW"|"MEDIUM"|"HIGH"; adjustmentFactors:StakeAdjustmentFactor[]; cappedBy:"NONE"|"MAX_SINGLE_BET"|"DAILY_EXPOSURE"|"LEAGUE_EXPOSURE"|"CORRELATION_RISK"|"DRAWDOWN_CONTROL"|"MIN_STAKE"|"NO_BET"; status:"STAKE_ALLOWED"|"STAKE_REDUCED"|"STAKE_BLOCKED"|"NO_BET"; warnings:string[]; reasons:string[] }
export interface PortfolioExposure { date:string; bankroll:number; activeRecommendationCount:number; totalStake:number; totalStakePct:number; exposureByLeague:Array<{league:string; stake:number; stakePct:number; recommendationCount:number}>; exposureByOutcomeType:Array<{outcome:"HOME"|"DRAW"|"AWAY"; stake:number; stakePct:number; recommendationCount:number}>; exposureByRiskLevel:Array<{riskLevel:RiskLevel; stake:number; stakePct:number; recommendationCount:number}>; maxSingleBetStake:number; maxSingleBetStakePct:number; dailyLimitUsedPct:number; warnings:string[] }
export interface ExposureLimitCheck { allowed:boolean; limitType:"MAX_SINGLE_BET"|"MAX_DAILY_EXPOSURE"|"MAX_LEAGUE_EXPOSURE"|"MAX_OUTCOME_TYPE_EXPOSURE"|"CORRELATION_LIMIT"; currentExposure:number; proposedStake:number; limit:number; remainingCapacity:number; adjustedStake:number; reason:string }
export interface CorrelationRiskOutput { correlationRiskLevel:"LOW"|"MEDIUM"|"HIGH"; correlatedRecommendationIds:string[]; correlationFactors:Array<{factor:"SAME_LEAGUE"|"SAME_KICKOFF_WINDOW"|"SAME_OUTCOME_TYPE"|"LOW_ODDS_FAVORITES"|"SAME_MARKET_SIGNAL"|"SAME_EXTERNAL_MARKET_QUALITY"|"SAME_MODEL_WEAKNESS"; severity:"LOW"|"MEDIUM"|"HIGH"; description:string}>; stakeReductionFactor:number; warnings:string[] }
export interface DrawdownState { currentEquity:number; peakEquity:number; currentDrawdown:number; currentDrawdownPct:number; maxDrawdown:number; maxDrawdownPct:number; consecutiveLosses:number; riskMode:"NORMAL"|"CAUTION"|"DEFENSIVE"|"PAUSED"; stakeMultiplier:number; warnings:string[] }
export interface BankrollTransaction { id:string; bankrollId:string; matchId?:string; officialMatchId?:string; type:"STAKE_PLACED"|"BET_WON"|"BET_LOST"|"BET_VOID"|"MANUAL_ADJUSTMENT"|"BANKROLL_RESET"; amount:number; bankrollBefore:number; bankrollAfter:number; createdAt:string; note?:string }
export type ThreeWayEv = ThreeWayProbability;
export type EvTriple = ThreeWayEv;
export type FairOddsTriple = OfficialSp;
export type DevigMethod = "MULTIPLICATIVE"|"ADDITIVE"|"POWER"|"ODDS_RATIO"|"SHIN"|"CONSERVATIVE";
export interface DevigProbabilitySet { method:DevigMethod; probability:ThreeWayProbability; fairOdds:ThreeWayOdds; overround:number; valid:boolean; warnings:string[] }
export interface MultiDevigResult { source:string; odds:ThreeWayOdds; methods:Record<DevigMethod,DevigProbabilitySet>; recommendedMethod:DevigMethod; recommendedProbability:ThreeWayProbability; recommendedFairOdds:ThreeWayOdds; methodAgreementScore:number; methodSpread:ThreeWayProbability&{max:number}; warnings:string[] }
export interface ProbabilityUncertainty { mean:ThreeWayProbability; lower:ThreeWayProbability; upper:ThreeWayProbability; std:ThreeWayProbability; confidence:ThreeWayProbability; methodSpread:ThreeWayProbability&{max?:number}; modelDisagreement:ThreeWayProbability; sampleReliability:number; overallUncertainty:number; warnings:string[] }
export interface EdgeQualityOutput { outcome:"HOME"|"DRAW"|"AWAY"|"NO_BET"; officialSp:number; breakEvenProbability:number; estimatedProbability:number; lowerBoundProbability:number; upperBoundProbability:number; expectedEv:number; lowerBoundEv:number; upperBoundEv:number; expectedClosingEdge?:number|null; clvWinProbability?:number|null; edgeQualityScore:number; edgeQualityLevel:"HIGH"|"MEDIUM"|"LOW"|"NO_EDGE"; edgeNoiseRisk:RiskLevel; adaptiveThreshold:number; passesTrueOddsFilter:boolean; reasons:string[]; warnings:string[] }
export interface TrueOddsEstimate { matchId:string; officialMatchId:string; createdAt:string; marketMultiDevig:MultiDevigResult; externalMultiDevig?:MultiDevigResult; baseProbability:ThreeWayProbability; biasCorrectedProbability:ThreeWayProbability; uncertainty:ProbabilityUncertainty; trueProbabilityEstimate:ThreeWayProbability; trueFairOdds:ThreeWayOdds; edgeQualityByOutcome:Record<"HOME"|"DRAW"|"AWAY",EdgeQualityOutput>; selectedEdge:EdgeQualityOutput; closingLineProxy?:unknown; marketBiasBucket?:unknown; drawCalibration?:{applied:boolean; drawDelta:number; [key:string]:unknown}; warnings:string[] }
export interface TrueOddsFilterConfig { configId:string; name:string; lowerBoundEvMin:number; edgeQualityMinScore:number; allowedEdgeQualityLevels:Array<EdgeQualityOutput["edgeQualityLevel"]>; uncertaintyZ:number; minMethodAgreementScore:number; baseEvThreshold:number; drawExtraThreshold:number; highOddsExtraThreshold:number; lowOddsExtraThreshold:number; requirePositiveExpectedClv:boolean; minClvWinProbability?:number|null; mode:"SHADOW"|"FILTER_ONLY"|"ADJUST_PROBABILITY"; warnings:string[] }
export interface EdgeBucketPerformance { bucketName:string; bucketType:string; sampleCount:number; recommendationCount:number; passedCount:number; blockedCount:number; roi:number|null; averageClv:number|null; positiveClvRate:number|null; hitRate:number|null; averageEdgeQualityScore:number|null; averageLowerBoundEv:number|null; maxDrawdown:number|null; warnings:string[] }
export interface BlockedRecommendationAnalysis { blockedCount:number; blockedRatio:number; blockedRoi:number|null; blockedAverageClv:number|null; blockedPositiveClvRate:number|null; blockedHitRate:number|null; blockedAverageExpectedEv:number|null; blockedAverageLowerBoundEv:number|null; wouldHaveLostCount:number; wouldHaveWonCount:number; estimatedLossAvoided:number|null; summary:string[]; warnings:string[] }
export interface TrueOddsOptimizationResult { runId:string; createdAt:string; baselineMetrics:Record<string,number>; variantResults:Array<{variantId:string; name:string; config:TrueOddsFilterConfig; metrics:Record<string,number>}>; bestConfig?:TrueOddsFilterConfig; bestVariantId?:string; ranking:Array<{variantId:string; name:string; score:number; metrics:Record<string,number>; reasons:string[]; config:TrueOddsFilterConfig}>; blockedAnalysis:BlockedRecommendationAnalysis; bucketPerformance:EdgeBucketPerformance[]; recommendedForProduction:boolean; promotionDecision:"KEEP_CURRENT"|"ENABLE_FILTER_ONLY"|"NEED_MORE_DATA"|"REJECT_TRUE_ODDS_FILTER"|"SHADOW_ONLY"; promotionReasons:string[]; warnings:string[] }

export interface HistoricalMatch {
  id: string; league: string; homeTeam: string; awayTeam: string;
  homeGoals: number; awayGoals: number; playedAt: string;
  matchType?: "LEAGUE" | "CUP" | "FRIENDLY" | "INTERNATIONAL" | "UNKNOWN";
  homeXg?: number; awayXg?: number; homeRedCards?: number; awayRedCards?: number;
  homeEloBefore?: number; awayEloBefore?: number; venue?: string; neutralVenue?: boolean;
}
export type EnhancedHistoricalMatch = HistoricalMatch;

export interface NewsEvent {
  id: string; team: "HOME" | "AWAY";
  type: "INJURY" | "SUSPENSION" | "RETURN" | "TACTICAL" | "MOTIVATION";
  playerName?: string; playerImportance?: "CORE" | "STARTER" | "ROTATION" | "BACKUP";
  position?: "GK" | "DEF" | "MID" | "FWD";
  impact: number; confidence: number; source: string; publishedAt: string;
}

export interface WeatherContext {
  condition: "CLEAR" | "CLOUDY" | "RAIN" | "HEAVY_RAIN" | "SNOW" | "WINDY";
  temperature: number; humidity: number; windSpeed: number;
  pitchCondition: "GOOD" | "NORMAL" | "POOR";
}

export interface MatchContext {
  newsEvents?: NewsEvent[]; weather?: WeatherContext;
  playerEvents?: PlayerImpactEvent[];
  homeRestDays?: number; awayRestDays?: number;
  homeTravelDistance?: number; awayTravelDistance?: number;
  lineupKnown?: boolean; dataFreshness?: "FRESH" | "STALE";
  newsReliability?: "HIGH" | "MEDIUM" | "LOW";
  isCupOrFriendly?: boolean; riskLimitTriggered?: boolean;
}

export interface ExpectedGoalsOutput {
  lambdaHome: number; lambdaAway: number;
  adjustmentDetails: {
    leagueAvgHomeGoals: number; leagueAvgAwayGoals: number;
    homeAttackStrength: number; awayAttackStrength: number;
    homeDefenseWeakness: number; awayDefenseWeakness: number;
    homeAdvantageFactor: number; newsAdjustmentHome: number; newsAdjustmentAway: number;
    weatherAdjustment: number; fatigueAdjustmentHome: number; fatigueAdjustmentAway: number;
    lineupPenalty: number;
  };
  dataReliability?: "LOW" | "MEDIUM" | "HIGH";
  homeSampleCount?: number; awaySampleCount?: number; warnings?: string[];
}

export interface ScoreProbability { homeGoals: number; awayGoals: number; probability: number }
export interface ModelDisagreement {
  homeDisagreement: number; drawDisagreement: number; awayDisagreement: number;
  maxDisagreement: number; level: RiskLevel;
}
export interface TeamHomeAwayStrength { team: string; homeAttackStrength: number; homeDefenseWeakness: number; awayAttackStrength: number; awayDefenseWeakness: number; overallAttackStrength: number; overallDefenseWeakness: number; homeWeightedMatches: number; awayWeightedMatches: number; totalWeightedMatches: number; homeReliability: number; awayReliability: number; overallReliability: number; warnings: string[] }
export interface LeagueAdvancedParameters { league: string; matchCount: number; avgHomeGoals: number; avgAwayGoals: number; avgTotalGoals: number; avgHomeXg?: number; avgAwayXg?: number; homeWinRate: number; drawRate: number; awayWinRate: number; baseDrawRate: number; fittedRho: number; rhoReliability: "HIGH" | "MEDIUM" | "LOW"; tempoFactor: number; goalVariance: number; reliability: "HIGH" | "MEDIUM" | "LOW"; warnings: string[] }
export interface LeagueParameters { league: string; matchCount: number; avgHomeGoals: number; avgAwayGoals: number; avgTotalGoals: number; homeWinRate: number; drawRate: number; awayWinRate: number; baseDrawRate: number; homeAdvantageFactor: number; defaultRho: number; reliability: "HIGH" | "MEDIUM" | "LOW"; fittedRho?:number; rhoReliability?:"HIGH"|"MEDIUM"|"LOW"; tempoFactor?:number; goalVariance?:number; warnings?:string[] }
export interface XgExpectedGoalsOutput { useXg: boolean; lambdaHomeFromXg?: number; lambdaAwayFromXg?: number; lambdaHomeFromGoals: number; lambdaAwayFromGoals: number; lambdaHome: number; lambdaAway: number; xgReliability: number; fallbackReason?: string; warnings: string[] }
export interface FormRating { team: string; attackForm: number; defenseForm: number; resultForm: number; xgForm?: number; opponentAdjustedForm: number; formReliability: number; recentMatches: number; warnings: string[] }
export interface FixtureFatigueOutput { homeFatigueFactor: number; awayFatigueFactor: number; homeRestDays?: number; awayRestDays?: number; homeMatchesLast7Days: number; awayMatchesLast7Days: number; homeMatchesLast14Days: number; awayMatchesLast14Days: number; homeConsecutiveAwayMatches: number; awayConsecutiveAwayMatches: number; homeTravelPenalty: number; awayTravelPenalty: number; riskLevel: RiskLevel; warnings: string[] }
export interface PlayerImpactEvent { id: string; team: "HOME" | "AWAY"; type: "INJURY" | "SUSPENSION" | "RETURN" | "DOUBTFUL" | "ROTATION"; playerName?: string; position?: "GK" | "DEF" | "MID" | "FWD"; importance?: "CORE" | "STARTER" | "ROTATION" | "BACKUP"; confidence: number; source?: string; publishedAt?: string }
export interface LineupImpactOutput { homeAttackFactor: number; homeDefenseFactor: number; awayAttackFactor: number; awayDefenseFactor: number; homeGoalkeeperRisk: number; awayGoalkeeperRisk: number; totalImpactMagnitude: number; riskLevel: RiskLevel; appliedEvents: Array<{eventId: string; description: string; factorType: string; factorChange: number}>; warnings: string[] }
export interface GlickoLikeRating { team: string; rating: number; ratingDeviation: number; reliability: "HIGH" | "MEDIUM" | "LOW"; recentTrend: number; matchCount: number }
export interface PureModelBreakdown { dixonColesProbability: ThreeWayProbability; eloProbability: ThreeWayProbability; glickoLikeProbability?: ThreeWayProbability; xgPoissonProbability?: ThreeWayProbability; pureModelProbability: ThreeWayProbability; lambdaHome: number; lambdaAway: number; homeStrength: TeamHomeAwayStrength; awayStrength: TeamHomeAwayStrength; leagueParameters: LeagueAdvancedParameters; form: {home: FormRating; away: FormRating}; fatigue: FixtureFatigueOutput; lineupImpact: LineupImpactOutput; modelWeights: {dixonColes: number; elo: number; glickoLike?: number; xgPoisson?: number}; reliability: "HIGH" | "MEDIUM" | "LOW"; lambdaClamped?: boolean; warnings: string[] }
export interface MarketDeviation { homeDeviation: number; drawDeviation: number; awayDeviation: number; maxDeviation: number }
export interface PredictionDiagnostics { homeMatchCount: number; awayMatchCount: number; leagueMatchCount: number; teamStatsReliability: "LOW" | "MEDIUM" | "HIGH"; eloReliability: "LOW" | "MEDIUM" | "HIGH"; leagueReliability: "LOW" | "MEDIUM" | "HIGH"; marketDeviation: MarketDeviation; deviationAfterAnchor: MarketDeviation; marketAnchored: boolean; ensembleWeights: {market: number; externalMarket?: number; pureModel?: number; dixonColes?: number; elo?: number; ml?: number}; warnings: string[] }
export interface CriticReport {
  passed: boolean; finalAction: RecommendationType; reasons: string[]; warnings: string[];
  dynamicEvThreshold: number; confidenceLevel: ConfidenceLevel; riskLevel: RiskLevel;
}

export interface StackingFeatureVector {
  matchId: string; officialMatchId: string; kickoffTime: string; league: string;
  marketHomeProb: number; marketDrawProb: number; marketAwayProb: number;
  externalHomeProb: number; externalDrawProb: number; externalAwayProb: number;
  pureHomeProb: number; pureDrawProb: number; pureAwayProb: number;
  dixonHomeProb?: number; dixonDrawProb?: number; dixonAwayProb?: number;
  eloHomeProb?: number; eloDrawProb?: number; eloAwayProb?: number;
  glickoHomeProb?: number; glickoDrawProb?: number; glickoAwayProb?: number;
  xgHomeProb?: number; xgDrawProb?: number; xgAwayProb?: number;
  officialSpHome: number; officialSpDraw: number; officialSpAway: number;
  marketFairOddsHome: number; marketFairOddsDraw: number; marketFairOddsAway: number;
  externalFairOddsHome: number; externalFairOddsDraw: number; externalFairOddsAway: number;
  pureFairOddsHome: number; pureFairOddsDraw: number; pureFairOddsAway: number;
  pureEdgeHome: number; pureEdgeDraw: number; pureEdgeAway: number;
  finalEdgeHome?: number; finalEdgeDraw?: number; finalEdgeAway?: number;
  maxMarketPureDeviation: number; maxExternalOfficialDeviation: number; maxSubModelDeviation: number;
  externalMarketQualityScore: number; externalMarketQualityLevelEncoded: number;
  pureModelReliabilityEncoded: number; leagueReliabilityEncoded: number; lineupRiskEncoded: number; fatigueRiskEncoded: number;
  homeStrengthReliability: number; awayStrengthReliability: number; xgUsed: number; fittedRho: number;
  lambdaHome: number; lambdaAway: number; lambdaDiff: number; lambdaTotal: number;
  isCup: number; isFriendly: number; isInternational: number; neutralVenue: number;
  actualResult?: "HOME" | "DRAW" | "AWAY";
}
export interface StackingTrainingExample { features: StackingFeatureVector; label: "HOME" | "DRAW" | "AWAY"; sampleWeight: number }
export interface StackingModelCoefficients {
  modelType: "MULTINOMIAL_LOGISTIC_REGRESSION"; featureNames: string[];
  homeWeights: number[]; drawWeights: number[]; awayWeights: number[];
  homeBias: number; drawBias: number; awayBias: number;
  featureMeans?: number[]; featureStds?: number[];
  trainedAt: string; trainingMatchCount: number; validationMatchCount: number;
  metrics: {trainLogLoss: number; validationLogLoss: number; validationBrierScore: number; validationCalibrationError: number};
  version: string;
}
export interface StackingPredictionOutput {
  available: boolean; probability: ThreeWayProbability; rawScores: ThreeWayProbability; confidence: number;
  modelVersion?: string; fallbackUsed: boolean; fallbackReason?: string;
  topFeatures?: Array<{feature: string; contribution: number}>; warnings: string[];
}
export interface StackingEvaluationResult {
  baselineMetrics: BacktestMetrics; stackingMetrics: BacktestMetrics;
  logLossImprovement: number; brierScoreImprovement: number; calibrationImprovement: number; roiDifference: number; clvDifference: number;
  byLeague: Array<{league: string; baselineLogLoss: number; stackingLogLoss: number; improvement: number; count: number}>;
  byRecommendationType: Array<{recommendation: RecommendationType; baselineLogLoss: number; stackingLogLoss: number; improvement: number; count: number}>;
  summary: string[];
}

export interface MatchPrediction {
  matchId: string; officialMatchId: string;
  officialSp: ThreeWayOdds;
  externalBookmakerOdds?: ExternalBookmakerOdds[];
  probabilityAvailable: boolean;
  marketProbability: ThreeWayProbability; externalMarketProbability: ThreeWayProbability;
  pureModelProbability: ThreeWayProbability; dixonColesProbability: ThreeWayProbability;
  poissonProbability: ThreeWayProbability; eloProbability: ThreeWayProbability;
  mlProbability?: ThreeWayProbability; finalProbability: ThreeWayProbability;
  pureModelBreakdown?: PureModelBreakdown;
  stackingPrediction?: StackingPredictionOutput; stackedProbability?: ThreeWayProbability;
  modelVersion?: string; probabilitySource?: "RULE_BASED_ENSEMBLE" | "STACKING_MODEL" | "STACKING_FALLBACK";
  officialSpSnapshotId?:string; externalOddsSnapshotId?:string; recalculationId?:string;
  lifecycleStatus?:RecommendationLifecycleStatus; marketMovementSignals?:MarketMovementSignal[]; auditLogIds?:string[];
  expectedGoals: ExpectedGoalsOutput; lambdaHome: number; lambdaAway: number;
  marketFairOdds: ThreeWayOdds; externalMarketFairOdds: ThreeWayOdds;
  externalMarketQuality: ExternalMarketQuality; externalMarketWarnings: string[];
  normalizedBookmakers: NormalizedBookmakerProbability[];
  pureModelFairOdds: ThreeWayOdds; finalFairOdds: ThreeWayOdds;
  pureModelEdge: ThreeWayEdge; finalEdge: ThreeWayEdge;
  /** @deprecated Use finalFairOdds. */
  fairOdds: ThreeWayOdds;
  ev: ThreeWayEv; topScores: ScoreProbability[];
  modelDisagreement: ModelDisagreement; dynamicEvThreshold: number; criticReport: CriticReport;
  trueOddsEstimate?: TrueOddsEstimate; edgeQuality?: EdgeQualityOutput; lowerBoundEv?: number; adaptiveEvThreshold?: number; passesTrueOddsFilter?: boolean; noBetReason?: string[];
  anchoredProbability: ThreeWayProbability; diagnostics: PredictionDiagnostics;
  criticPassed: boolean; criticReasons: string[];
  recommendation: RecommendationType; confidence: ConfidenceLevel; confidenceGrade: ConfidenceGrade; confidenceScore: number;
  riskLevel: RiskLevel; suggestedStake: number; stakeFraction: number; stakeRecommendation?:StakeRecommendation;
  recommendedProbability: number | null; recommendedSp: number | null; recommendedEv: number | null;
  createdAt: string;
}
export type ModelPrediction = MatchPrediction;

export interface TeamStats { team: string; league: string; elo: number; recentGoalsFor: number; recentGoalsAgainst: number; recentMatches: number }
export interface LeagueStats { league: string; avgHomeGoals: number; avgAwayGoals: number; avgTeamGoals: number }
export interface OfficialMatchFeatures {
  home_rating?: number; away_rating?: number; lambda_home?: number; lambda_away?: number;
  home_recent_matches?: number; away_recent_matches?: number;
  home_recent_goals_for?: number; home_recent_goals_against?: number;
  away_recent_goals_for?: number; away_recent_goals_against?: number;
  league_avg_home_goals?: number; league_avg_away_goals?: number; league_avg_team_goals?: number;
  source_confidence?: number;
  source_confidence_components?: {min_raw_matches?: number; raw_sample_reliability?: number; recent_sample_reliability?: number};
  [key: string]: unknown;
}
export interface NewsItem { title: string; url: string; publishedAt: string; confidence: number }
export interface WeatherData { temperature: number | null; humidity: number | null; rainfall: number | null; windSpeed: number | null; fetchedAt: string }
export interface LlmAnalysis { summary: string; homeTeamImpact: number; awayTeamImpact: number; lineupConfidence: number; newsConfidence: number; injuries: string[]; risks: string[]; evidence: string[]; model: string; createdAt: string }

export interface OfficialMatch {
  id: string; officialMatchId: string; league: string; homeTeam: string; awayTeam: string;
  kickoffTime: string; status: MatchStatus; officialSp: OfficialSp;
  externalBookmakerOdds?: ExternalBookmakerOdds[];
  homeElo?: number; awayElo?: number; updatedAt: string;
  marketOdds: ThreeWayProbability; news: NewsItem[]; weather: WeatherData | null;
  venue: string | null; llmAnalysis: LlmAnalysis | null; context?: MatchContext;
  features?: OfficialMatchFeatures;
  prediction: MatchPrediction; modelProbability: ThreeWayProbability; modelFairOdds: OfficialSp;
  ev: ThreeWayEv; recommendation: RecommendationType; confidence: string;
  riskLevel: RiskLevel; predictionType: string; marketCalibrated: boolean;
}

export interface AgentStatus { id: string; name: string; state: AgentState; successRate: number; latency: string; taskCount: number; lastUpdated: string }
export interface OddsSnapshot { matchId: string; time: string; home: number; draw: number; away: number }
export interface MatchResult { matchId: string; officialMatchId: string; homeGoals: number; awayGoals: number; result: "HOME" | "DRAW" | "AWAY"; settledAt: string }
export interface ClosingSp { matchId: string; officialMatchId: string; home: number; draw: number; away: number; capturedAt: string }
export interface BacktestInputMatch {
  id: string; officialMatchId: string; league: string; homeTeam: string; awayTeam: string; kickoffTime: string;
  officialSp: ThreeWayOdds; closingSp?: ThreeWayOdds; result?: MatchResult;
  externalBookmakerOdds?: ExternalBookmakerOdds[]; context?: MatchContext;
}
export interface BacktestRecord {
  matchId: string; officialMatchId: string; league: string; homeTeam: string; awayTeam: string; kickoffTime: string;
  prediction: MatchPrediction; actualResult?: "HOME" | "DRAW" | "AWAY"; recommendation: RecommendationType;
  selectedProbability?: number; selectedOfficialSp?: number; selectedClosingSp?: number; ev?: number;
  stake: number; profit: number; hit: boolean | null; clv?: number; clvPositive?: boolean | null;
  brierScore: number; logLoss: number; riskLevel: RiskLevel;
  externalMarketQualityLevel?: "HIGH" | "MEDIUM" | "LOW" | "UNAVAILABLE"; modelDisagreementLevel?: RiskLevel;
  pureModelEdge?: number; finalEdge?: number; noBetReason?: string[]; warnings?: string[];
  pureModelReliability?: "HIGH" | "MEDIUM" | "LOW"; leagueReliability?: "HIGH" | "MEDIUM" | "LOW";
  homeStrengthReliability?: number; awayStrengthReliability?: number; lineupRiskLevel?: RiskLevel; fatigueRiskLevel?: RiskLevel;
  xgUsed?: boolean; fittedRho?: number;
  probabilitySource?: MatchPrediction["probabilitySource"]; modelVersion?: string; stackingConfidence?: number;
  stackingFallbackUsed?: boolean; stackingTopFeatures?: Array<{feature: string; contribution: number}>;
  openingSp?:ThreeWayOdds; recommendationSp?:ThreeWayOdds; recommendationCreatedAt?:string; recommendationAgeMinutes?:number; recalculationCount?:number; marketMovementBeforeRecommendation?:boolean;
  edgeQualityLevel?:EdgeQualityOutput["edgeQualityLevel"]; edgeQualityScore?:number; lowerBoundEv?:number; adaptiveEvThreshold?:number; passesTrueOddsFilter?:boolean;
  bankrollBefore?:number; bankrollAfter?:number; suggestedStake?:number; stakePctOfBankroll?:number; stakeCappedBy?:StakeRecommendation["cappedBy"]; stakeStatus?:StakeRecommendation["status"]; drawdownState?:DrawdownState; portfolioExposureAtBet?:PortfolioExposure;
}
export interface BacktestMetrics {
  totalMatches: number; totalBets: number; noBetCount: number; noBetRatio: number; hitCount: number; hitRate: number;
  totalStake: number; totalProfit: number; roi: number; maxDrawdown: number; averageEv: number; averageClv: number;
  positiveClvRate: number; brierScore: number; logLoss: number; averagePredictedProbability: number;
  averageActualHitRate: number; calibrationError: number; finalBankroll?:number; bankrollGrowth?:number; bankrollGrowthPct?:number; averageStake?:number; medianStake?:number; maxStake?:number; stakeVolatility?:number; longestLosingStreak?:number; riskAdjustedRoi?:number; averageDailyExposure?:number; maxDailyExposure?:number; averageLeagueConcentration?:number; stakeBlockedCount?:number; stakeReducedCount?:number;
}
export interface CalibrationBucket { bucket: string; lowerBound: number; upperBound: number; count: number; avgPredictedProbability: number; actualHitRate: number; calibrationError: number }
export interface GroupedBacktestMetrics { groupName: string; count: number; metrics: BacktestMetrics }
export interface ErrorAnalysisReport {
  byLeague: GroupedBacktestMetrics[]; byRecommendationType: GroupedBacktestMetrics[]; byEvBucket: GroupedBacktestMetrics[];
  byProbabilityBucket: GroupedBacktestMetrics[]; byOfficialSpBucket: GroupedBacktestMetrics[]; byRiskLevel: GroupedBacktestMetrics[];
  byExternalMarketQuality: GroupedBacktestMetrics[]; byDisagreementLevel: GroupedBacktestMetrics[];
  byPureModelEdgeBucket: GroupedBacktestMetrics[]; byFinalEdgeBucket: GroupedBacktestMetrics[]; calibrationTable: CalibrationBucket[];
  byPureModelReliability: GroupedBacktestMetrics[]; byLeagueReliability: GroupedBacktestMetrics[]; byLineupRisk: GroupedBacktestMetrics[]; byFatigueRisk: GroupedBacktestMetrics[]; byXgUsed: GroupedBacktestMetrics[]; byRhoBucket: GroupedBacktestMetrics[];
  byStakeBucket?:GroupedBacktestMetrics[]; byStakeStatus?:GroupedBacktestMetrics[]; byCappedBy?:GroupedBacktestMetrics[]; byDrawdownRiskMode?:GroupedBacktestMetrics[]; byCorrelationRisk?:GroupedBacktestMetrics[];
  commonNoBetReasons: Array<{reason: string; count: number}>; commonWarnings: Array<{warning: string; count: number}>; summary: string[];
}
export interface TemperatureOptimizationResult { candidates: Array<{temperature: number; logLoss: number; brierScore: number; calibrationError: number}>; bestTemperature: number; bestLogLoss: number; previousTemperature: number; improvement: number }
export interface WalkForwardBacktestResult { records: BacktestRecord[]; metrics: BacktestMetrics; calibrationTable: CalibrationBucket[]; errorAnalysis: ErrorAnalysisReport; temperatureOptimization?: TemperatureOptimizationResult }
export interface BankrollRecord { id: string; date: string; match: string; stake: number; result: string; profit: number; balance: number }
export interface Recommendation { matchId: string; type: RecommendationType; confidence: string; stake: string; riskReason: string }
export interface RiskAlert { id: string; matchId: string; level: RiskLevel; title: string; detail: string; createdAt: string }
export interface WorkflowNode { id: string; name: string; state: AgentState; lastRun: string; success: boolean }
export interface RuleStrategy { id: string; label: string; value: string | number | boolean; description: string }
export interface NotificationItem { id: string; type: string; title: string; content: string; createdAt: string; read: boolean }
export interface AuditLogItem { id: string; time: string; operator: string; module: string; action: string; detail: string; result: string }
