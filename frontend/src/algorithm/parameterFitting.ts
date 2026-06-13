import type {HistoricalMatch, LeagueParameters} from "../types";
import {estimateAllLeagueParameters} from "./leagueParameters";
import {splitHistoricalDataByTime} from "./timeSplit";
export function fitAlgorithmParameters(matches: HistoricalMatch[]) {
  const split = splitHistoricalDataByTime(matches);
  const leagueParameters: Record<string, LeagueParameters> = estimateAllLeagueParameters(split.train);
  return {leagueParameters, trainSize: split.train.length, validationSize: split.validation.length, testSize: split.test.length};
}
