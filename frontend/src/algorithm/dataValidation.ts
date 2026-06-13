import type {HistoricalMatch, OfficialMatch} from "../types";
const statuses = new Set(["NOT_STARTED", "LIVE", "FINISHED", "CANCELLED", "POSTPONED", "CLOSED"]);
export function validateOfficialMatch(match: Pick<OfficialMatch, "officialMatchId" | "homeTeam" | "awayTeam" | "kickoffTime" | "status" | "officialSp">) {
  const errors: string[] = [], warnings: string[] = [];
  if (!match.officialMatchId) errors.push("缺少官方比赛 ID。");
  if (!match.homeTeam || !match.awayTeam) errors.push("主客队名称不能为空。");
  if (match.homeTeam && match.homeTeam === match.awayTeam) errors.push("主队和客队不能相同。");
  if (!match.kickoffTime || !Number.isFinite(new Date(match.kickoffTime).getTime())) errors.push("开赛时间无效。");
  if (!statuses.has(match.status)) errors.push("比赛状态无效。");
  if (!match.officialSp || Object.values(match.officialSp).some(value => !Number.isFinite(value) || value <= 1)) errors.push("官方 SP 无效。");
  return {valid: errors.length === 0, errors, warnings};
}
export function validateHistoricalMatches(matches: HistoricalMatch[]) {
  const validMatches: HistoricalMatch[] = [], droppedMatches: Array<{match: HistoricalMatch; reasons: string[]}> = [], warnings: string[] = [], seen = new Set<string>();
  const teamCoverage: Record<string, {matchCount: number; firstMatchDate: string; lastMatchDate: string}> = {};
  const now = Date.now();
  for (const match of matches) {
    const reasons: string[] = [], date = new Date(match.playedAt).getTime();
    if (!Number.isFinite(match.homeGoals) || !Number.isFinite(match.awayGoals) || match.homeGoals < 0 || match.awayGoals < 0) reasons.push("比分无效");
    if (!Number.isFinite(date)) reasons.push("日期无效"); else if (date > now) reasons.push("未来比赛");
    if (!match.homeTeam || !match.awayTeam || match.homeTeam === match.awayTeam) reasons.push("球队名称无效");
    const key = `${match.playedAt}|${match.homeTeam}|${match.awayTeam}`;
    if (seen.has(key)) reasons.push("重复比赛"); else seen.add(key);
    if (reasons.length) { droppedMatches.push({match, reasons}); continue; }
    validMatches.push(match);
    for (const team of [match.homeTeam, match.awayTeam]) {
      const row = teamCoverage[team] ?? {matchCount: 0, firstMatchDate: match.playedAt, lastMatchDate: match.playedAt};
      row.matchCount += 1; row.firstMatchDate = row.firstMatchDate < match.playedAt ? row.firstMatchDate : match.playedAt; row.lastMatchDate = row.lastMatchDate > match.playedAt ? row.lastMatchDate : match.playedAt; teamCoverage[team] = row;
    }
  }
  for (const [team, coverage] of Object.entries(teamCoverage)) if (coverage.matchCount < 10) warnings.push(`${team} 历史场次少于 10 场。`);
  return {validMatches, droppedMatches, warnings, teamCoverage};
}
