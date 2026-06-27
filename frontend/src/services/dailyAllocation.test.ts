import {describe, expect, it} from "vitest";
import {buildDailyAllocationPlan} from "../algorithm/dailyAllocation";
import type {OfficialMatch, RecommendationType} from "../types";

const match = (id: string, recommendation: RecommendationType, ev: number, passed = true): OfficialMatch => ({
  id, officialMatchId: `O-${id}`, league: "L", homeTeam: `H-${id}`, awayTeam: `A-${id}`,
  kickoffTime: "2027-01-01T12:00:00Z", status: "NOT_STARTED", officialSp: {home: 2, draw: 3.5, away: 4},
  context: {dataFreshness: "FRESH"}, recommendation, riskLevel: "LOW",
  prediction: {
    recommendation, probabilityAvailable: true, finalProbability: {home: .5 + ev / 2, draw: .28, away: .22 - ev / 2},
    ev: {home: ev, draw: -.02, away: -.12}, riskLevel: "LOW", confidenceGrade: recommendation === "NO_BET" ? "NO_BET" : "A",
    criticReport: {passed, reasons: passed ? [] : ["hard rule blocked"]}, passesTrueOddsFilter: passed,
    edgeQuality: {edgeQualityScore: 70}, lifecycleStatus: recommendation === "NO_BET" ? "NO_BET" : "ACTIVE",
    stakeRecommendation: recommendation === "NO_BET" ? undefined : {status: "STAKE_ALLOWED", finalStake: 35},
  },
} as unknown as OfficialMatch);

const shadowMatch = (id = "1"): OfficialMatch => {
  const row = match(id, "NO_BET", -.2, false);
  row.prediction.finalProbability = {home: .36, draw: .28, away: .36};
  row.prediction.ev = {home: -.28, draw: -.02, away: .44};
  return row;
};

describe("daily allocation", () => {
  it("keeps the budget as cash when no match passes hard rules", () => {
    const plan = buildDailyAllocationPlan([shadowMatch()], 100);
    expect(plan.executableAllocated).toBe(0);
    expect(plan.cashReserve).toBe(100);
    expect(plan.shadowSimulated[0].mode).toBe("SHADOW_ONLY");
  });

  it("keeps unavailable model output in shadow mode only", () => {
    const row = shadowMatch();
    row.prediction.probabilityAvailable = false;
    const plan = buildDailyAllocationPlan([row], 100);
    expect(plan.executable).toHaveLength(0);
    expect(plan.shadowSimulated).toHaveLength(1);
  });

  it("does not force non-positive EV selections into research mode", () => {
    const plan = buildDailyAllocationPlan([match("1", "NO_BET", -.02, false)], 100);
    expect(plan.executable).toHaveLength(0);
    expect(plan.shadowSimulated).toHaveLength(0);
  });

  it("uses fixed 20 stakes and enforces the 100 daily ceiling", () => {
    const plan = buildDailyAllocationPlan([shadowMatch("1"), shadowMatch("2"), shadowMatch("3")], 500);
    expect(plan.budget).toBe(100);
    expect(plan.shadowSimulated.map(row => row.amount)).toEqual([20, 20, 20]);
  });

  it("does not exceed the approved Kelly stake", () => {
    const row = match("1", "HOME", .12);
    row.prediction.stakeRecommendation!.finalStake = 3;
    const plan = buildDailyAllocationPlan([row], 100);
    expect(plan.executable[0].amount).toBe(3);
    expect(plan.cashReserve).toBe(97);
  });

  it("allocates only to executable candidates and respects the 35% single cap", () => {
    const plan = buildDailyAllocationPlan([
      match("1", "HOME", .15), match("2", "HOME", .10), match("3", "HOME", .08), match("4", "NO_BET", .20, false),
    ], 100);
    expect(plan.executable).toHaveLength(3);
    expect(plan.executable.every(row => row.amount <= 35)).toBe(true);
    expect(plan.executable.reduce((sum, row) => sum + row.amount, 0)).toBeCloseTo(100, 1);
    expect(plan.executable.some(row => row.matchId === "4")).toBe(false);
  });
});
