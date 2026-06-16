import {describe,expect,it} from "vitest";
import {createDefaultBankrollConfig} from "../algorithm/bankrollManager";
import {checkMaxDailyExposureLimit,checkMaxLeagueExposureLimit,checkMaxOutcomeTypeExposureLimit,checkMaxSingleBetLimit} from "../algorithm/exposureLimits";
const config=createDefaultBankrollConfig(), exposure={totalStake:4.8,exposureByLeague:[{league:"L",stake:2.4}],exposureByOutcomeType:[{outcome:"HOME",stake:2.4}]} as any;
describe("exposure limits",()=>{it("caps single bet",()=>expect(checkMaxSingleBetLimit(2,config).adjustedStake).toBe(1));it("caps daily, league and outcome exposure",()=>{expect(checkMaxDailyExposureLimit(1,config,exposure).adjustedStake).toBeCloseTo(.2);expect(checkMaxLeagueExposureLimit(1,config,exposure,"L").adjustedStake).toBeCloseTo(.1);expect(checkMaxOutcomeTypeExposureLimit(1,config,exposure,"HOME").adjustedStake).toBeCloseTo(.1)});});
