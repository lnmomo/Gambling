import type {HistoricalMatch, OfficialMatch} from "../types";
import {teamAliasMap} from "./config";

const clean = (name: string) => name.trim().replace(/\s+/g, " ");
export function normalizeTeamName(name: string): string {
  const value = clean(name || "");
  return teamAliasMap[value] ?? teamAliasMap[value.toLowerCase()] ?? value;
}
export function normalizeMatchTeams<T extends Pick<OfficialMatch, "homeTeam" | "awayTeam">>(match: T): T {
  return {...match, homeTeam: normalizeTeamName(match.homeTeam), awayTeam: normalizeTeamName(match.awayTeam)};
}
export function normalizeHistoricalMatches(matches: HistoricalMatch[]): HistoricalMatch[] {
  return matches.map(match => ({...match, homeTeam: normalizeTeamName(match.homeTeam), awayTeam: normalizeTeamName(match.awayTeam)}));
}
