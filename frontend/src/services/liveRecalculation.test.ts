import {describe, expect, it} from "vitest";
import {buildLiveRecalculationResult, shouldRecalculatePrediction} from "../algorithm/liveRecalculation";
import {calculateMatchPrediction} from "../algorithm/probabilityEngine";
import {demoBacktestMatches, demoWalkForwardHistory} from "../data/backtestData";
const match={...demoBacktestMatches[0],kickoffTime:"2027-01-01T12:00:00Z",status:"NOT_STARTED" as const,marketOdds:{home:0,draw:0,away:0},updatedAt:new Date().toISOString()};
describe("live recalculation",()=>{it("recalculates on explicit market triggers",()=>{const prediction=calculateMatchPrediction(match,demoWalkForwardHistory,match.context??{}),trigger={id:"t",matchId:match.id,officialMatchId:match.officialMatchId,triggeredAt:new Date().toISOString(),type:"OFFICIAL_SP_CHANGED" as const,severity:"MEDIUM" as const,description:"SP changed"};expect(shouldRecalculatePrediction(prediction,trigger,[]).shouldRecalculate).toBe(true);expect(buildLiveRecalculationResult(match,trigger,prediction,prediction).probabilityDelta.maxDelta).toBe(0)});});
