import {calculateMatchPrediction, calculatePredictionForMatch, clamp} from "../services/probabilityEngine";
import {limitDailyRecommendations} from "../algorithm/criticRules";
import {normalizeTeamName} from "../algorithm/teamNameNormalizer";
import type {ExternalBookmakerOdds, HistoricalMatch, LeagueStats, MatchContext, MatchStatus, OfficialMatch, OfficialSp, TeamStats} from "../types";

interface ApiMatch {id: number; official_match_id: string; league: string; home_team: string; away_team: string; kickoff_time: string; status: string; last_seen_at: string | null; official_odds: Partial<OfficialSp>; odds_fetched_at: string | null; market_odds: Partial<OfficialSp>; external_bookmaker_odds?: Array<{bookmaker: string; bookmaker_key?: string; market: string; odds: OfficialSp; last_update: string; source?: string}>; news: Array<{raw_text: string; source_url: string; published_at: string; confidence: number}>; weather: {temperature: number | null; humidity: number | null; rainfall: number | null; wind_speed: number | null; fetched_at: string} | null; metadata: {venue: string | null; city: string | null} | null; llm_analysis: {model: string; created_at: string; analysis: {summary: string; home_team_impact: number; away_team_impact: number; lineup_confidence: number; news_confidence: number; injuries: string[]; risks: string[]; evidence: string[]}} | null; features: Record<string, unknown>}
const statusMap: Record<string, MatchStatus> = {scheduled: "NOT_STARTED", live: "LIVE", finished: "FINISHED", cancelled: "CANCELLED", postponed: "POSTPONED", closed: "CLOSED", unknown: "CLOSED"};
const num = (value: unknown, fallback = 0) => typeof value === "number" && Number.isFinite(value) ? value : fallback;

function contextFor(row: ApiMatch): MatchContext {
  const llm = row.llm_analysis?.analysis, confidence = llm?.news_confidence ?? 0, weather = row.weather;
  const rainfall = num(weather?.rainfall), wind = num(weather?.wind_speed);
  const condition = rainfall >= 8 ? "HEAVY_RAIN" : rainfall >= 1 ? "RAIN" : wind >= 20 ? "WINDY" : "CLEAR";
  const fetchedAt = row.odds_fetched_at ? new Date(row.odds_fetched_at).getTime() : 0;
  return {
    newsEvents: llm && confidence >= .4 ? [
      {id: `${row.id}-home`, team: "HOME", type: "TACTICAL", impact: clamp(llm.home_team_impact, -.08, .08), confidence, source: "LLM news extraction", publishedAt: row.llm_analysis?.created_at ?? ""},
      {id: `${row.id}-away`, team: "AWAY", type: "TACTICAL", impact: clamp(llm.away_team_impact, -.08, .08), confidence, source: "LLM news extraction", publishedAt: row.llm_analysis?.created_at ?? ""},
    ] : [],
    weather: weather ? {condition, temperature: num(weather.temperature, 18), humidity: num(weather.humidity), windSpeed: wind, pitchCondition: rainfall >= 8 ? "POOR" : "NORMAL"} : undefined,
    newsReliability: llm ? confidence >= .75 ? "HIGH" : confidence >= .4 ? "MEDIUM" : "LOW" : undefined,
    lineupKnown: llm ? llm.lineup_confidence >= .6 : true,
    dataFreshness: fetchedAt && Date.now() - fetchedAt <= 10 * 60_000 ? "FRESH" : "STALE",
    isCupOrFriendly: /杯|友谊|国际赛/i.test(row.league),
  };
}

function teamStats(row: ApiMatch, side: "home" | "away"): TeamStats | undefined {
  const f = row.features ?? {}, recentMatches = num(f[`${side}_recent_matches`]);
  if (!recentMatches && typeof f[`${side}_rating`] !== "number") return undefined;
  return {team: side === "home" ? row.home_team : row.away_team, league: row.league, elo: num(f[`${side}_rating`], 1500), recentGoalsFor: num(f[`${side}_recent_goals_for`]), recentGoalsAgainst: num(f[`${side}_recent_goals_against`]), recentMatches};
}
function leagueStats(row: ApiMatch): LeagueStats | undefined {
  const f = row.features ?? {};
  if (typeof f.league_avg_home_goals !== "number" && typeof f.league_avg_away_goals !== "number") return undefined;
  return {league: row.league, avgHomeGoals: num(f.league_avg_home_goals, 1.45), avgAwayGoals: num(f.league_avg_away_goals, 1.15), avgTeamGoals: num(f.league_avg_team_goals, 1.3)};
}

interface ApiHistoricalMatch {id: string; league: string; home_team: string; away_team: string; home_goals: number; away_goals: number; played_at: string; match_type: "LEAGUE" | "CUP" | "FRIENDLY"|"INTERNATIONAL"|"UNKNOWN";home_xg?:number;away_xg?:number;home_red_cards?:number;away_red_cards?:number;home_elo_before?:number;away_elo_before?:number;venue?:string;neutral_venue?:boolean}
const mapHistoricalMatch = (row: ApiHistoricalMatch): HistoricalMatch => ({id: row.id, league: row.league, homeTeam: row.home_team, awayTeam: row.away_team, homeGoals: row.home_goals, awayGoals: row.away_goals, playedAt: row.played_at, matchType: row.match_type,homeXg:row.home_xg,awayXg:row.away_xg,homeRedCards:row.home_red_cards,awayRedCards:row.away_red_cards,homeEloBefore:row.home_elo_before,awayEloBefore:row.away_elo_before,venue:row.venue,neutralVenue:row.neutral_venue});

export function mapOfficialMatch(row: ApiMatch, historicalMatches: HistoricalMatch[] = []): OfficialMatch {
  const officialSp = {home: num(row.official_odds.home), draw: num(row.official_odds.draw), away: num(row.official_odds.away)};
  const marketOdds = {home: num(row.market_odds.home), draw: num(row.market_odds.draw), away: num(row.market_odds.away)};
  const externalBookmakerOdds: ExternalBookmakerOdds[] = (row.external_bookmaker_odds ?? []).map(item => ({bookmaker: item.bookmaker, bookmakerKey: item.bookmaker_key, market: item.market === "1X2" ? "1X2" : "H2H", odds: item.odds, lastUpdate: item.last_update, source: item.source}));
  const home = teamStats(row, "home"), away = teamStats(row, "away"), context = contextFor(row);
  const base = {id: String(row.id), officialMatchId: row.official_match_id, league: row.league, homeTeam: row.home_team, awayTeam: row.away_team, kickoffTime: row.kickoff_time, status: statusMap[row.status] ?? "CLOSED", officialSp, externalBookmakerOdds, homeElo: home?.elo, awayElo: away?.elo, updatedAt: row.odds_fetched_at ?? row.last_seen_at ?? "", marketOdds, news: (row.news ?? []).map(item => ({title: item.raw_text, url: item.source_url, publishedAt: item.published_at, confidence: item.confidence})), weather: row.weather ? {temperature: row.weather.temperature, humidity: row.weather.humidity, rainfall: row.weather.rainfall, windSpeed: row.weather.wind_speed, fetchedAt: row.weather.fetched_at} : null, venue: row.metadata?.venue ?? row.metadata?.city ?? null, llmAnalysis: row.llm_analysis ? {summary: row.llm_analysis.analysis.summary, homeTeamImpact: row.llm_analysis.analysis.home_team_impact, awayTeamImpact: row.llm_analysis.analysis.away_team_impact, lineupConfidence: row.llm_analysis.analysis.lineup_confidence, newsConfidence: row.llm_analysis.analysis.news_confidence, injuries: row.llm_analysis.analysis.injuries, risks: row.llm_analysis.analysis.risks, evidence: row.llm_analysis.analysis.evidence, model: row.llm_analysis.model, createdAt: row.llm_analysis.created_at} : null, context};
  const teams: Record<string, TeamStats> = {};
  if (home) teams[row.home_team] = home;
  if (away) teams[row.away_team] = away;
  const leagues: Record<string, LeagueStats> = {};
  const league = leagueStats(row);
  if (league) leagues[row.league] = league;
  const prediction = historicalMatches.length ? calculateMatchPrediction(base, historicalMatches, context, 10_000) : calculatePredictionForMatch(base, teams, leagues, {[base.id]: context});
  return {...base, prediction, modelProbability: prediction.finalProbability, modelFairOdds: prediction.finalFairOdds, ev: prediction.ev, recommendation: prediction.recommendation, confidence: prediction.confidenceGrade, riskLevel: prediction.riskLevel, predictionType: "official market + external market + pure model", marketCalibrated: Object.values(marketOdds).every(value => value > 1)};
}

export async function fetchOfficialMatches(signal?: AbortSignal): Promise<OfficialMatch[]> {
  const officialResponse = await fetch("/api/official/matches", {signal});
  if (!officialResponse.ok) throw new Error(`官方比赛接口请求失败 (${officialResponse.status})`);
  const officialRows = (await officialResponse.json()) as ApiMatch[];
  const teams = [...new Set(officialRows.flatMap(row => [normalizeTeamName(row.home_team), normalizeTeamName(row.away_team)]))];
  const query = new URLSearchParams({limit: "100000", teams: teams.join(",")});
  const historyResponse = await fetch(`/api/historical-matches?${query}`, {signal});
  if (!historyResponse.ok) throw new Error(`历史比赛接口请求失败 (${historyResponse.status})`);
  const history = ((await historyResponse.json()) as ApiHistoricalMatch[]).map(mapHistoricalMatch);
  const matches = officialRows.map(row => mapOfficialMatch(row, history));
  const limited = new Map(limitDailyRecommendations(matches.map(match => match.prediction)).map(prediction => [prediction.matchId, prediction]));
  return matches.map(match => { const prediction = limited.get(match.id) ?? match.prediction; return {...match, prediction, recommendation: prediction.recommendation, ev: prediction.ev, riskLevel: prediction.riskLevel, confidence: prediction.confidenceGrade}; });
}
