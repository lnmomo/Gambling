import {describe,expect,it} from "vitest";
import {calculateCorrelationRisk} from "../algorithm/correlationRisk";
const p=(id:string,league="L",recommendation="HOME",odds=1.4)=>({matchId:id,officialMatchId:id,league,kickoffTime:"2027-01-01T12:00:00Z",recommendation,officialSp:{home:odds,draw:3,away:5},externalMarketQuality:{qualityLevel:"HIGH"}} as any);
describe("correlation risk",()=>{it("detects same league and low odds concentration",()=>{const risk=calculateCorrelationRisk(p("c"),[p("1"),p("2"),p("3")]);expect(risk.correlationRiskLevel).not.toBe("LOW");expect(risk.stakeReductionFactor).toBeLessThan(1)});it("is low without obvious correlation",()=>expect(calculateCorrelationRisk(p("c","A"),[p("1","B","AWAY",3)]).correlationRiskLevel).toBe("LOW"));});
