import type {MatchStatus,OfficialMatch,Recommendation} from "../types";

interface OfficialMatchResponse {
  id:number;
  official_match_id:string;
  league:string;
  home_team:string;
  away_team:string;
  kickoff_time:string;
  status:string;
  last_seen_at:string|null;
  official_odds:Partial<Record<"home"|"draw"|"away",number>>;
  market_odds:Partial<Record<"home"|"draw"|"away",number>>;
  prediction:{model_name:string;p_home:number;p_draw:number;p_away:number;fair_odds_home:number|null;fair_odds_draw:number|null;fair_odds_away:number|null;metadata?:{market_calibrated?:boolean}}|null;
  signal:{status:string;option:"home"|"draw"|"away"|null;confidence:string}|null;
  news:Array<{raw_text:string;source_url:string;published_at:string;confidence:number}>;
  weather:{temperature:number|null;humidity:number|null;rainfall:number|null;wind_speed:number|null;fetched_at:string}|null;
  metadata:{venue:string|null;city:string|null}|null;
  llm_analysis:{model:string;created_at:string;analysis:{summary:string;home_team_impact:number;away_team_impact:number;lineup_confidence:number;news_confidence:number;injuries:string[];risks:string[];evidence:string[]}}|null;
}

const statusMap:Record<string,MatchStatus>={
  scheduled:"NOT_STARTED",live:"LIVE",finished:"FINISHED",cancelled:"CANCELLED",
  postponed:"POSTPONED",closed:"CLOSED",unknown:"CLOSED"
};

export function mapOfficialMatch(row:OfficialMatchResponse):OfficialMatch {
  const prediction={home:row.prediction?.p_home??0,draw:row.prediction?.p_draw??0,away:row.prediction?.p_away??0};
  const modelFairOdds={home:row.prediction?.fair_odds_home??0,draw:row.prediction?.fair_odds_draw??0,away:row.prediction?.fair_odds_away??0};
  const marketCalibrated=row.prediction?.model_name==="ensemble";
  const recommendation=row.signal?.status==="BET"&&row.signal.option?row.signal.option.toUpperCase() as "HOME"|"DRAW"|"AWAY":"NO_BET";
  const officialSp={home:row.official_odds.home??0,draw:row.official_odds.draw??0,away:row.official_odds.away??0};
  return {
    id:String(row.id),officialMatchId:row.official_match_id,league:row.league,
    homeTeam:row.home_team,awayTeam:row.away_team,kickoffTime:row.kickoff_time,
    status:statusMap[row.status]??"CLOSED",
    officialSp,marketOdds:{home:row.market_odds.home??0,draw:row.market_odds.draw??0,away:row.market_odds.away??0},
    modelProbability:prediction,modelFairOdds,predictionType:row.prediction?.model_name??null,marketCalibrated,
    ev:marketCalibrated?{home:prediction.home*officialSp.home-1,draw:prediction.draw*officialSp.draw-1,away:prediction.away*officialSp.away-1}:{home:0,draw:0,away:0},
    recommendation,confidence:row.signal?.confidence??"-",riskLevel:row.signal?.status==="BET"?"LOW":"MEDIUM",
    updatedAt:row.last_seen_at??"-",news:(row.news??[]).map(item=>({title:item.raw_text,url:item.source_url,publishedAt:item.published_at,confidence:item.confidence})),
    weather:row.weather?{temperature:row.weather.temperature,humidity:row.weather.humidity,rainfall:row.weather.rainfall,windSpeed:row.weather.wind_speed,fetchedAt:row.weather.fetched_at}:null,
    venue:row.metadata?.venue??row.metadata?.city??null,
    llmAnalysis:row.llm_analysis?{summary:row.llm_analysis.analysis.summary,homeTeamImpact:row.llm_analysis.analysis.home_team_impact,awayTeamImpact:row.llm_analysis.analysis.away_team_impact,lineupConfidence:row.llm_analysis.analysis.lineup_confidence,newsConfidence:row.llm_analysis.analysis.news_confidence,injuries:row.llm_analysis.analysis.injuries,risks:row.llm_analysis.analysis.risks,evidence:row.llm_analysis.analysis.evidence,model:row.llm_analysis.model,createdAt:row.llm_analysis.created_at}:null
  };
}

export async function fetchOfficialMatches(signal?:AbortSignal):Promise<OfficialMatch[]> {
  const response=await fetch("/api/official/matches",{signal});
  if(!response.ok)throw new Error(`官方比赛接口请求失败 (${response.status})`);
  return ((await response.json()) as OfficialMatchResponse[]).map(mapOfficialMatch);
}

export function toNoBetRecommendation(match:OfficialMatch):Recommendation {
  return {matchId:match.id,type:"NO_BET",confidence:"-",stake:"0%",riskReason:"尚无完整模型预测，暂不推荐"};
}
