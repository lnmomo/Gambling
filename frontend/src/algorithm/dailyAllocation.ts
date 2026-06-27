import type {OfficialMatch, RecommendationType, RiskLevel} from "../types";

type Outcome = Exclude<RecommendationType, "NO_BET">;

export interface DailyAllocationItem {
  matchId: string;
  officialMatchId: string;
  league: string;
  match: string;
  kickoffTime: string;
  outcome: Outcome;
  probability: number;
  officialSp: number;
  ev: number;
  riskLevel: RiskLevel;
  score: number;
  amount: number;
  mode: "EXECUTABLE" | "SHADOW_ONLY";
  reasons: string[];
}

export interface DailyAllocationPlan {
  date: string;
  budget: number;
  executableAllocated: number;
  cashReserve: number;
  executable: DailyAllocationItem[];
  shadowSimulated: DailyAllocationItem[];
  warnings: string[];
}

type AllocationCandidate = Omit<DailyAllocationItem, "amount"> & {allocationCap?: number};
const DAILY_INVESTMENT_LIMIT = 100;
const SHADOW_POLICY = {outcome: "AWAY", minOdds: 1.5, maxOdds: 5, maxModelMarketGap: .18, minConservativeEv: .03, stakePerPick: 20} as const;

const keyOf = (outcome: Outcome) => outcome === "HOME" ? "home" : outcome === "DRAW" ? "draw" : "away";
const outcomeOf = (match: OfficialMatch): Outcome => {
  const rows = [
    {outcome: "HOME" as const, ev: match.prediction.ev.home},
    {outcome: "DRAW" as const, ev: match.prediction.ev.draw},
    {outcome: "AWAY" as const, ev: match.prediction.ev.away},
  ];
  return rows.sort((a, b) => b.ev - a.ev)[0].outcome;
};
const confidenceFactor = {A: 1, B: .82, C: .58, D: .35, NO_BET: .25} as const;
const riskFactor = {LOW: 1, MEDIUM: .68, HIGH: .35} as const;
const roundMoney = (value: number) => Math.round((value + Number.EPSILON) * 100) / 100;

function validPreMatch(match: OfficialMatch, mode: DailyAllocationItem["mode"]): boolean {
  const probability = match.prediction.finalProbability;
  const hasCalculatedProbability = Object.values(probability).every(value => Number.isFinite(value) && value > 0)
    && Math.abs(probability.home + probability.draw + probability.away - 1) < .01;
  return match.status === "NOT_STARTED"
    && (mode === "SHADOW_ONLY" ? hasCalculatedProbability : match.prediction.probabilityAvailable)
    && match.context?.dataFreshness !== "STALE"
    && Object.values(match.officialSp).every(value => Number.isFinite(value) && value > 1);
}

function candidate(match: OfficialMatch, mode: DailyAllocationItem["mode"]): AllocationCandidate | null {
  if (!validPreMatch(match, mode)) return null;
  const recommended = match.prediction.recommendation;
  const outcome = mode === "EXECUTABLE" && recommended !== "NO_BET" ? recommended : outcomeOf(match);
  const key = keyOf(outcome), ev = match.prediction.ev[key];
  if (!Number.isFinite(ev) || (mode === "EXECUTABLE" && ev <= 0)) return null;
  let allocationCap: number | undefined;
  if (mode === "EXECUTABLE") {
    if (!match.prediction.criticReport.passed || recommended === "NO_BET") return null;
    if (match.prediction.passesTrueOddsFilter === false) return null;
    const stake = match.prediction.stakeRecommendation;
    if (!stake || !["STAKE_ALLOWED", "STAKE_REDUCED"].includes(stake.status) || stake.finalStake <= 0) return null;
    allocationCap = stake.finalStake;
  } else {
    const inverse = {home: 1 / match.officialSp.home, draw: 1 / match.officialSp.draw, away: 1 / match.officialSp.away};
    const inverseTotal = inverse.home + inverse.draw + inverse.away;
    const marketProbability = inverse[key] / inverseTotal;
    const modelMarketGap = Math.abs(match.prediction.finalProbability[key] - marketProbability);
    const conservativeEv = (match.prediction.finalProbability[key] - .05 * modelMarketGap) * match.officialSp[key] - 1;
    if (outcome !== SHADOW_POLICY.outcome) return null;
    if (match.officialSp[key] < SHADOW_POLICY.minOdds || match.officialSp[key] > SHADOW_POLICY.maxOdds) return null;
    if (modelMarketGap > SHADOW_POLICY.maxModelMarketGap || conservativeEv < SHADOW_POLICY.minConservativeEv) return null;
  }
  const edgeScore = match.prediction.edgeQuality?.edgeQualityScore ?? 40;
  const confidence = confidenceFactor[match.prediction.confidenceGrade] ?? .25;
  const score = Math.exp(Math.max(-1, Math.min(1, ev * 5))) * confidence * riskFactor[match.prediction.riskLevel] * (.5 + edgeScore / 100);
  return {
    matchId: match.id,
    officialMatchId: match.officialMatchId,
    league: match.league,
    match: `${match.homeTeam} vs ${match.awayTeam}`,
    kickoffTime: match.kickoffTime,
    outcome,
    probability: match.prediction.finalProbability[key],
    officialSp: match.officialSp[key],
    ev,
    riskLevel: match.prediction.riskLevel,
    score,
    mode,
    reasons: mode === "EXECUTABLE"
      ? ["通过 Critic、True Odds Filter 与 Kelly 资金风控"]
      : [...match.prediction.criticReport.reasons, ...(ev <= 0 ? ["最高 EV 非正，仅保留为研究样本。"] : [])],
    allocationCap,
  };
}

function allocate(rows: AllocationCandidate[], budget: number, mode: DailyAllocationItem["mode"]): DailyAllocationItem[] {
  const selected = rows.sort((a, b) => b.score - a.score).slice(0, 5);
  if (!selected.length || budget <= 0) return [];
  if (mode === "SHADOW_ONLY") {
    let remaining = budget;
    return selected.map(({allocationCap: _allocationCap, ...row}) => {
      const amount = roundMoney(Math.min(SHADOW_POLICY.stakePerPick, remaining));
      remaining -= amount;
      return {...row, amount};
    }).filter(row => row.amount > 0);
  }
  const capFor = (row: AllocationCandidate) => Math.min(budget * .35, row.allocationCap ?? Number.POSITIVE_INFINITY);
  const amounts = new Map(selected.map(row => [row.matchId, 0]));
  let remaining = budget, active = [...selected];
  while (remaining >= .01 && active.length) {
    const totalScore = active.reduce((sum, row) => sum + row.score, 0);
    let distributed = 0;
    for (const row of active) {
      const current = amounts.get(row.matchId) ?? 0;
      const share = remaining * row.score / totalScore;
      const addition = Math.min(share, capFor(row) - current);
      if (addition > 0) {
        amounts.set(row.matchId, current + addition);
        distributed += addition;
      }
    }
    remaining -= distributed;
    active = active.filter(row => (amounts.get(row.matchId) ?? 0) < capFor(row) - .001);
    if (distributed < .001) break;
  }
  return selected.map(({allocationCap: _allocationCap, ...row}) => ({...row, amount: roundMoney(amounts.get(row.matchId) ?? 0)})).filter(row => row.amount > 0);
}

export function buildDailyAllocationPlan(matches: OfficialMatch[], budget = 100, now = new Date()): DailyAllocationPlan {
  const cleanBudget = Math.min(DAILY_INVESTMENT_LIMIT, Math.max(0, Number.isFinite(budget) ? budget : 0));
  const executableRows = matches.map(match => candidate(match, "EXECUTABLE")).filter(Boolean) as AllocationCandidate[];
  const executable = allocate(executableRows, cleanBudget, "EXECUTABLE");
  const executableIds = new Set(executable.map(row => row.matchId));
  const shadowRows = matches
    .filter(match => !executableIds.has(match.id))
    .map(match => candidate(match, "SHADOW_ONLY"))
    .filter(Boolean) as AllocationCandidate[];
  const shadowSimulated = allocate(shadowRows, cleanBudget, "SHADOW_ONLY");
  const executableAllocated = roundMoney(executable.reduce((sum, row) => sum + row.amount, 0));
  const cashReserve = roundMoney(Math.max(0, cleanBudget - executableAllocated));
  const warnings: string[] = [];
  if (!executable.length) warnings.push("当前没有通过全部硬规则的候选，实际额度保持现金。下方仅为影子模拟，不应用于真实执行。");
  if (executable.length < 3 && executableAllocated < cleanBudget) warnings.push("单场上限为每日预算的 35%，未分配部分保留现金。可执行候选不足时不会强制满仓。");
  warnings.push("改进影子策略每日上限 100 元、单笔 20 元；没有满足保守 EV、赔率区间和验证方向的标的时不强制投入。");
  return {date: now.toISOString().slice(0, 10), budget: roundMoney(cleanBudget), executableAllocated, cashReserve, executable, shadowSimulated, warnings};
}
