export type MatchStatus = "NOT_STARTED" | "LIVE" | "FINISHED" | "CANCELLED" | "POSTPONED" | "CLOSED";
export type RecommendationType = "HOME" | "DRAW" | "AWAY" | "NO_BET";
export type BetOption = RecommendationType;
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";
export type ConfidenceLevel = "A" | "B" | "C" | "D";
export type ConfidenceGrade = ConfidenceLevel | "NO_BET";
export type AgentState = "RUNNING" | "DELAYED" | "WARNING";

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
export type ThreeWayEv = ThreeWayProbability;
export type EvTriple = ThreeWayEv;
export type FairOddsTriple = OfficialSp;

export interface HistoricalMatch {
  id: string; league: string; homeTeam: string; awayTeam: string;
  homeGoals: number; awayGoals: number; playedAt: string;
  matchType?: "LEAGUE" | "CUP" | "FRIENDLY";
}

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
export interface LeagueParameters { league: string; matchCount: number; avgHomeGoals: number; avgAwayGoals: number; avgTotalGoals: number; homeWinRate: number; drawRate: number; awayWinRate: number; baseDrawRate: number; homeAdvantageFactor: number; defaultRho: number; reliability: "LOW" | "MEDIUM" | "HIGH" }
export interface MarketDeviation { homeDeviation: number; drawDeviation: number; awayDeviation: number; maxDeviation: number }
export interface PredictionDiagnostics { homeMatchCount: number; awayMatchCount: number; leagueMatchCount: number; teamStatsReliability: "LOW" | "MEDIUM" | "HIGH"; eloReliability: "LOW" | "MEDIUM" | "HIGH"; leagueReliability: "LOW" | "MEDIUM" | "HIGH"; marketDeviation: MarketDeviation; deviationAfterAnchor: MarketDeviation; marketAnchored: boolean; ensembleWeights: {market: number; externalMarket?: number; pureModel?: number; dixonColes?: number; elo?: number; ml?: number}; warnings: string[] }
export interface CriticReport {
  passed: boolean; finalAction: RecommendationType; reasons: string[]; warnings: string[];
  dynamicEvThreshold: number; confidenceLevel: ConfidenceLevel; riskLevel: RiskLevel;
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
  anchoredProbability: ThreeWayProbability; diagnostics: PredictionDiagnostics;
  criticPassed: boolean; criticReasons: string[];
  recommendation: RecommendationType; confidence: ConfidenceLevel; confidenceGrade: ConfidenceGrade; confidenceScore: number;
  riskLevel: RiskLevel; suggestedStake: number; stakeFraction: number;
  recommendedProbability: number | null; recommendedSp: number | null; recommendedEv: number | null;
  createdAt: string;
}
export type ModelPrediction = MatchPrediction;

export interface TeamStats { team: string; league: string; elo: number; recentGoalsFor: number; recentGoalsAgainst: number; recentMatches: number }
export interface LeagueStats { league: string; avgHomeGoals: number; avgAwayGoals: number; avgTeamGoals: number }
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
  prediction: MatchPrediction; modelProbability: ThreeWayProbability; modelFairOdds: OfficialSp;
  ev: ThreeWayEv; recommendation: RecommendationType; confidence: string;
  riskLevel: RiskLevel; predictionType: string; marketCalibrated: boolean;
}

export interface AgentStatus { id: string; name: string; state: AgentState; successRate: number; latency: string; taskCount: number; lastUpdated: string }
export interface OddsSnapshot { matchId: string; time: string; home: number; draw: number; away: number }
export interface BacktestRecord { id: string; date: string; match: string; recommendation: RecommendationType; sp: number; probability: number; ev: number; result: string; profit: number; strategy: string }
export interface BankrollRecord { id: string; date: string; match: string; stake: number; result: string; profit: number; balance: number }
export interface Recommendation { matchId: string; type: RecommendationType; confidence: string; stake: string; riskReason: string }
export interface RiskAlert { id: string; matchId: string; level: RiskLevel; title: string; detail: string; createdAt: string }
export interface WorkflowNode { id: string; name: string; state: AgentState; lastRun: string; success: boolean }
export interface RuleStrategy { id: string; label: string; value: string | number | boolean; description: string }
export interface NotificationItem { id: string; type: string; title: string; content: string; createdAt: string; read: boolean }
export interface AuditLogItem { id: string; time: string; operator: string; module: string; action: string; detail: string; result: string }
