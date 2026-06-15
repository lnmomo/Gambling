import {describe, expect, it} from "vitest";
import {determineRecommendationLifecycle} from "../algorithm/recommendationLifecycle";
import type {MatchPrediction} from "../types";
const prediction=(recommendation:"HOME"|"AWAY"|"NO_BET",ev=.1)=>({recommendation,recommendedEv:ev} as MatchPrediction);
describe("recommendation lifecycle",()=>{it("withdraws a recommendation that becomes NO_BET",()=>expect(determineRecommendationLifecycle(prediction("HOME"),prediction("NO_BET"),"NOT_STARTED").status).toBe("WITHDRAWN"));it("marks stale snapshots",()=>expect(determineRecommendationLifecycle(undefined,prediction("HOME"),"NOT_STARTED",{snapshotStale:true}).status).toBe("STALE"));it("closes finished matches",()=>expect(determineRecommendationLifecycle(undefined,prediction("HOME"),"FINISHED").status).toBe("CLOSED"));});
