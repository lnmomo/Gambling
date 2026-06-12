export type MatchStatus="NOT_STARTED"|"LIVE"|"FINISHED"|"CANCELLED"|"POSTPONED"|"CLOSED";
export type BetOption="HOME"|"DRAW"|"AWAY"|"NO_BET";
export type RecommendationType=BetOption;
export type RiskLevel="LOW"|"MEDIUM"|"HIGH";
export type AgentState="RUNNING"|"DELAYED"|"WARNING";
export type ConfidenceGrade="A"|"B"|"C"|"D"|"NO_BET";

export interface ProbabilityTriple{home:number;draw:number;away:number}
export type ModelProbability=ProbabilityTriple;
export type OfficialSp=ProbabilityTriple;
export type EvTriple=ProbabilityTriple;
export type FairOddsTriple=ProbabilityTriple;

export interface TeamStats{team:string;league:string;elo:number;recentGoalsFor:number;recentGoalsAgainst:number;recentMatches:number;formScore?:number;restDays?:number;injuriesImpact?:number;lineupKnown?:boolean}
export interface LeagueStats{league:string;avgHomeGoals:number;avgAwayGoals:number;avgTeamGoals:number}
export interface MatchContext{weatherGoalFactor?:number;homeNewsAdjustment?:number;awayNewsAdjustment?:number;scheduleFatigueFactorHome?:number;scheduleFatigueFactorAway?:number;newsReliability?:"HIGH"|"MEDIUM"|"LOW";lineupKnown?:boolean;isCupOrFriendly?:boolean;riskLimitTriggered?:boolean}

export interface ModelPrediction{
  matchId:string;officialMatchId:string;marketProbability:ProbabilityTriple;poissonProbability:ProbabilityTriple;
  eloProbability:ProbabilityTriple;finalProbability:ProbabilityTriple;lambdaHome:number;lambdaAway:number;
  fairOdds:FairOddsTriple;ev:EvTriple;modelDisagreement:number;criticPassed:boolean;criticReasons:string[];
  recommendation:BetOption;recommendedProbability:number|null;recommendedSp:number|null;recommendedEv:number|null;
  confidenceScore:number;confidenceGrade:ConfidenceGrade;stakeFraction:number;createdAt:string;
}

export interface NewsItem{title:string;url:string;publishedAt:string;confidence:number}
export interface WeatherData{temperature:number|null;humidity:number|null;rainfall:number|null;windSpeed:number|null;fetchedAt:string}
export interface LlmAnalysis{summary:string;homeTeamImpact:number;awayTeamImpact:number;lineupConfidence:number;newsConfidence:number;injuries:string[];risks:string[];evidence:string[];model:string;createdAt:string}

export interface OfficialMatch{
  id:string;officialMatchId:string;league:string;homeTeam:string;awayTeam:string;kickoffTime:string;status:MatchStatus;
  officialSp:OfficialSp;updatedAt:string;marketOdds:ProbabilityTriple;news:NewsItem[];weather:WeatherData|null;
  venue:string|null;llmAnalysis:LlmAnalysis|null;homeStats?:TeamStats;awayStats?:TeamStats;context?:MatchContext;
  prediction:ModelPrediction;modelProbability:ProbabilityTriple;modelFairOdds:FairOddsTriple;ev:EvTriple;
  recommendation:BetOption;confidence:string;riskLevel:RiskLevel;predictionType:string;marketCalibrated:boolean;
}

export interface OddsSnapshot{matchId:string;time:string;home:number;draw:number;away:number}
export interface Recommendation{matchId:string;type:RecommendationType;confidence:string;stake:string;riskReason:string}
export interface RiskAlert{id:string;matchId:string;level:RiskLevel;title:string;detail:string;createdAt:string}
export interface AgentStatus{id:string;name:string;state:AgentState;successRate:number;latency:string;taskCount:number;lastUpdated:string}
export interface WorkflowNode{id:string;name:string;state:AgentState;lastRun:string;success:boolean}
export interface BacktestRecord{id:string;date:string;match:string;recommendation:RecommendationType;sp:number;probability:number;ev:number;result:string;profit:number;strategy:string}
export interface BankrollRecord{id:string;date:string;match:string;stake:number;result:string;profit:number;balance:number}
export interface RuleStrategy{id:string;label:string;value:string|number|boolean;description:string}
export interface NotificationItem{id:string;type:string;title:string;content:string;createdAt:string;read:boolean}
export interface AuditLogItem{id:string;time:string;operator:string;module:string;action:string;detail:string;result:string}
