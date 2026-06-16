import {describe,expect,it} from "vitest";
import {runWalkForwardBacktest} from "../algorithm/backtestEngine";
import {demoBacktestMatches,demoWalkForwardHistory} from "../data/backtestData";
describe("backtest bankroll",()=>{it("records bankroll and stake status without NaN",()=>{const result=runWalkForwardBacktest(demoBacktestMatches.slice(0,4),demoWalkForwardHistory,{bankroll:100});expect(result.records.every(row=>Number.isFinite(row.bankrollBefore)&&Number.isFinite(row.bankrollAfter))).toBe(true);expect(result.metrics.finalBankroll).toBeDefined();expect(result.metrics.longestLosingStreak).toBeGreaterThanOrEqual(0);});});
