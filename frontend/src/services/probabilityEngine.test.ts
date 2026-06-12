import {describe,expect,it} from "vitest";
import {calculateElo1x2,calculateEv,calculateFairOdds,calculateModelDisagreement,calculatePoisson1x2,calculatePredictionForMatch,ensembleProbabilities,impliedProbabilityFromSp,normalizeTriple,runCriticChecks} from "./probabilityEngine";
import type {OfficialMatch,ProbabilityTriple} from "../types";

const sum=(p:ProbabilityTriple)=>p.home+p.draw+p.away;
const match=(overrides:Partial<OfficialMatch>={})=>({id:"1",officialMatchId:"J001",league:"测试联赛",homeTeam:"主队",awayTeam:"客队",status:"NOT_STARTED",officialSp:{home:2.1,draw:3.2,away:3.4},updatedAt:new Date().toISOString(),...overrides} as OfficialMatch);

describe("probability engine",()=>{
  it("normalizes every probability triple",()=>expect(sum(normalizeTriple({home:2,draw:1,away:1}))).toBeCloseTo(1,10));
  it("removes the bookmaker margin from official SP",()=>expect(sum(impliedProbabilityFromSp({home:1.8,draw:3.5,away:4.2}))).toBeCloseTo(1,10));
  it("returns normalized Poisson and Elo probabilities",()=>{expect(sum(calculatePoisson1x2(1.7,1.1))).toBeCloseTo(1,8);expect(sum(calculateElo1x2(1600,1500))).toBeCloseTo(1,8)});
  it("uses the configured 45/35/20 ensemble",()=>{const result=ensembleProbabilities({home:.5,draw:.3,away:.2},{home:.4,draw:.3,away:.3},{home:.6,draw:.2,away:.2});expect(result.home).toBeCloseTo(.485,8);expect(sum(result)).toBeCloseTo(1,8)});
  it("calculates fair odds and EV",()=>{expect(calculateFairOdds({home:.5,draw:.3,away:.2}).home).toBe(2);expect(calculateEv({home:.5,draw:.3,away:.2},{home:2.2,draw:3,away:4}).home).toBeCloseTo(.1)});
  it("detects model disagreement above 12%",()=>expect(calculateModelDisagreement({home:.6,draw:.2,away:.2},{home:.4,draw:.3,away:.3},{home:.5,draw:.25,away:.25})).toBeCloseTo(.2));
  it("forces No Bet without an official match id",()=>expect(calculatePredictionForMatch(match({officialMatchId:""}),{},{},{}).recommendation).toBe("NO_BET"));
  it("forces No Bet for a closed match",()=>expect(calculatePredictionForMatch(match({status:"CLOSED"}),{},{},{}).recommendation).toBe("NO_BET"));
  it("rejects stale data and low EV",()=>{const result=runCriticChecks(match({updatedAt:"2020-01-01T00:00:00Z"}),{finalProbability:{home:.45,draw:.3,away:.25},ev:{home:0,draw:-.04,away:-.1},modelDisagreement:.05});expect(result.passed).toBe(false);expect(result.reasons).toContain("官方赔率更新时间超过10分钟");expect(result.reasons).toContain("最高 EV 低于5%阈值")});
  it("changes the final probability when official SP changes",()=>{const a=calculatePredictionForMatch(match(),{},{},{}),b=calculatePredictionForMatch(match({officialSp:{home:1.5,draw:4.2,away:6}}),{},{},{});expect(a.finalProbability.home).not.toBeCloseTo(b.finalProbability.home,4)});
});
