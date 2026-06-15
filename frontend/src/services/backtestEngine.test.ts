import {describe, expect, it} from "vitest";
import {runWalkForwardBacktest} from "../algorithm/backtestEngine";
import {assertNoFutureLeakage, getPastMatchesOnly} from "../algorithm/timeSplit";
import {demoBacktestMatches, demoWalkForwardHistory} from "../data/backtestData";
describe("walk-forward engine", () => {
  it("only exposes history before each cutoff", () => { const cutoff = demoBacktestMatches[3].kickoffTime, past = getPastMatchesOnly(demoWalkForwardHistory, cutoff); expect(past.every(match => Date.parse(match.playedAt) < Date.parse(cutoff))).toBe(true); expect(assertNoFutureLeakage(past, cutoff).valid).toBe(true); });
  it("creates one record per input and metrics", () => { const result = runWalkForwardBacktest(demoBacktestMatches.slice(0, 4), demoWalkForwardHistory); expect(result.records).toHaveLength(4); expect(result.metrics.totalMatches).toBe(4); });
  it("sets NO_BET stake and profit to zero", () => { const result = runWalkForwardBacktest(demoBacktestMatches, demoWalkForwardHistory); for (const row of result.records.filter(item => item.recommendation === "NO_BET")) { expect(row.stake).toBe(0); expect(row.profit).toBe(0); } });
  it("settles wins and losses with the selected official SP", () => { const bets = runWalkForwardBacktest(demoBacktestMatches, demoWalkForwardHistory).records.filter(row => row.recommendation !== "NO_BET"); for (const row of bets) expect(row.profit).toBeCloseTo(row.hit ? row.stake * (row.selectedOfficialSp! - 1) : -row.stake); });
  it("only computes hit and CLV when source data exists", () => { const input = {...demoBacktestMatches[0], result: undefined, closingSp: undefined}; const row = runWalkForwardBacktest([input], demoWalkForwardHistory).records[0]; expect(row.hit).toBeNull(); expect(row.clv).toBeUndefined(); });
});
