import {describe,expect,it} from "vitest";
import {calculatePortfolioExposure} from "../algorithm/portfolioRisk";
const pred=(id:string,league:string,stake:number)=>({matchId:id,officialMatchId:id,league,recommendation:"HOME",lifecycleStatus:"ACTIVE",riskLevel:"LOW",stakeRecommendation:{finalStake:stake,status:"STAKE_ALLOWED"}} as any);
describe("portfolio risk",()=>{it("groups active recommendations by league and total stake",()=>{const exposure=calculatePortfolioExposure([pred("1","A",1),pred("2","A",2),{...pred("3","B",5),recommendation:"NO_BET"}],100);expect(exposure.totalStake).toBe(3);expect(exposure.exposureByLeague.find(row=>row.league==="A")?.recommendationCount).toBe(2)});});
