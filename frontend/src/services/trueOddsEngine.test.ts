import {describe, expect, it} from "vitest";
import {calculateMatchPrediction} from "../algorithm/probabilityEngine";
import {calculateTrueOddsEstimate} from "../algorithm/trueOddsEngine";
import type {HistoricalMatch, OfficialMatch} from "../types";

const match: Pick<OfficialMatch, "id"|"officialMatchId"|"league"|"homeTeam"|"awayTeam"|"kickoffTime"|"status"|"officialSp"|"marketOdds"|"externalBookmakerOdds"|"updatedAt"|"features"> = {
  id: "m1", officialMatchId: "M1", league: "Test", homeTeam: "A", awayTeam: "B",
  kickoffTime: "2027-01-01T12:00:00Z", status: "NOT_STARTED", officialSp: {home: 2.1, draw: 3.2, away: 3.4},
  marketOdds: {home: .45, draw: .29, away: .26}, externalBookmakerOdds: [], updatedAt: "2026-01-01T00:00:00Z",
  features: {home_rating: 1560, away_rating: 1480, lambda_home: 1.6, lambda_away: 1.0, home_recent_matches: 30, away_recent_matches: 30},
};
const history: HistoricalMatch[] = Array.from({length: 40}, (_, index) => ({
  id: String(index), league: "Test", homeTeam: index % 2 ? "A" : "B", awayTeam: index % 2 ? "B" : "A",
  homeGoals: index % 3, awayGoals: index % 2, playedAt: `2025-01-${String((index % 28) + 1).padStart(2, "0")}T12:00:00Z`,
}));

describe("calculateTrueOddsEstimate", () => {
  it("generates true odds diagnostics and keeps EV semantics in probability engine", () => {
    const prediction = calculateMatchPrediction(match, history, {}, 10000, {trueOddsMode: "SHADOW"});
    const estimate = calculateTrueOddsEstimate(match, prediction);
    expect(estimate.trueProbabilityEstimate.home + estimate.trueProbabilityEstimate.draw + estimate.trueProbabilityEstimate.away).toBeCloseTo(1, 8);
    expect(estimate.edgeQualityByOutcome.HOME).toBeDefined();
    expect(prediction.ev.home).toBeCloseTo(prediction.finalProbability.home * prediction.officialSp.home - 1, 8);
  });

  it("attaches true odds estimate in FILTER_ONLY mode", () => {
    const prediction = calculateMatchPrediction(match, history, {}, 10000, {trueOddsMode: "FILTER_ONLY"});
    expect(prediction.trueOddsEstimate).toBeDefined();
    expect(prediction.edgeQuality).toBeDefined();
    expect(typeof prediction.passesTrueOddsFilter).toBe("boolean");
  });
});
