import type {ExternalBookmakerOdds, ExternalMarketConsensus, ExternalMarketDeviation, ExternalMarketQuality, NormalizedBookmakerProbability, ThreeWayOdds, ThreeWayProbability} from "../types";
import {normalizeProbability} from "./ensembleModel";

export const DEFAULT_BOOKMAKER_WEIGHTS: Record<string, number> = {
  pinnacle: 1.35, betfair: 1.30, bet365: 1.10, williamhill: 1.00, unibet: 1.00,
  draftkings: .95, fanduel: .95, bovada: .85, other: .75,
};

const emptyProbability = {home: 0, draw: 0, away: 0};
export const fairOddsFromProbability = (p: ThreeWayProbability): ThreeWayOdds => {
  const normalized = normalizeProbability(p);
  return {home: 1 / normalized.home, draw: 1 / normalized.draw, away: 1 / normalized.away};
};
export const isValidThreeWayOdds = (odds: ThreeWayOdds) => [odds?.home, odds?.draw, odds?.away].every(value => Number.isFinite(value) && value > 1.01 && value <= 100);
export function isOddsStale(lastUpdate: string, maxAgeMinutes = 30, now = Date.now()) {
  const timestamp = new Date(lastUpdate).getTime();
  return !Number.isFinite(timestamp) || now - timestamp > maxAgeMinutes * 60_000;
}

export function convertBookmakerOddsToProbability(book: ExternalBookmakerOdds, options: {defaultWeight?: number; maxOverround?: number; maxAgeMinutes?: number; now?: number} = {}): NormalizedBookmakerProbability {
  const rawOdds = book.odds, rawImpliedProbability = isValidThreeWayOdds(rawOdds) ? {home: 1 / rawOdds.home, draw: 1 / rawOdds.draw, away: 1 / rawOdds.away} : emptyProbability;
  const sumRaw = rawImpliedProbability.home + rawImpliedProbability.draw + rawImpliedProbability.away;
  const overround = sumRaw - 1;
  const key = (book.bookmakerKey ?? book.bookmaker).toLowerCase().replace(/[^a-z0-9]/g, "");
  const weight = book.weight ?? DEFAULT_BOOKMAKER_WEIGHTS[key] ?? options.defaultWeight ?? DEFAULT_BOOKMAKER_WEIGHTS.other;
  let included = true, exclusionReason: string | undefined;
  if (!isValidThreeWayOdds(rawOdds)) { included = false; exclusionReason = "Invalid odds"; }
  else if (overround <= 0) { included = false; exclusionReason = "Invalid overround"; }
  else if (overround > (options.maxOverround ?? .18)) { included = false; exclusionReason = "Overround too high"; }
  else if (isOddsStale(book.lastUpdate, options.maxAgeMinutes ?? 30, options.now)) { included = false; exclusionReason = "Stale odds"; }
  const normalizedProbability = sumRaw > 0 ? {home: rawImpliedProbability.home / sumRaw, draw: rawImpliedProbability.draw / sumRaw, away: rawImpliedProbability.away / sumRaw} : {home: 1 / 3, draw: 1 / 3, away: 1 / 3};
  return {bookmaker: book.bookmaker, bookmakerKey: book.bookmakerKey, rawOdds, rawImpliedProbability, normalizedProbability, overround, weight, included, exclusionReason, lastUpdate: book.lastUpdate};
}

const median = (values: number[]) => { const sorted = [...values].sort((a, b) => a - b), middle = Math.floor(sorted.length / 2); return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2; };
export function detectOutlierBookmakers(rows: NormalizedBookmakerProbability[], options: {maxDeviationFromMedian?: number} = {}) {
  const included = rows.filter(row => row.included);
  if (included.length < 3) return rows;
  const medians = {home: median(included.map(row => row.normalizedProbability.home)), draw: median(included.map(row => row.normalizedProbability.draw)), away: median(included.map(row => row.normalizedProbability.away))};
  const limit = options.maxDeviationFromMedian ?? .10;
  return rows.map(row => {
    if (!row.included) return row;
    const deviation = Math.max(Math.abs(row.normalizedProbability.home - medians.home), Math.abs(row.normalizedProbability.draw - medians.draw), Math.abs(row.normalizedProbability.away - medians.away));
    return deviation > limit ? {...row, included: false, exclusionReason: "Outlier odds"} : row;
  });
}

export function calculateWeightedConsensusProbability(rows: NormalizedBookmakerProbability[], fallbackProbability: ThreeWayProbability) {
  const included = rows.filter(row => row.included);
  if (!included.length) return {probability: fallbackProbability, fallbackUsed: true, fallbackReason: "No valid external bookmaker odds"};
  const weightSum = included.reduce((sum, row) => sum + row.weight, 0);
  return {probability: normalizeProbability({home: included.reduce((sum, row) => sum + row.normalizedProbability.home * row.weight, 0) / weightSum, draw: included.reduce((sum, row) => sum + row.normalizedProbability.draw * row.weight, 0) / weightSum, away: included.reduce((sum, row) => sum + row.normalizedProbability.away * row.weight, 0) / weightSum}), fallbackUsed: false};
}

export function calculateProbabilityDeviation(a: ThreeWayProbability, b: ThreeWayProbability): ExternalMarketDeviation {
  const homeDeviation = Math.abs(a.home - b.home), drawDeviation = Math.abs(a.draw - b.draw), awayDeviation = Math.abs(a.away - b.away);
  return {homeDeviation, drawDeviation, awayDeviation, maxDeviation: Math.max(homeDeviation, drawDeviation, awayDeviation)};
}

export function calculateExternalMarketQuality(rows: NormalizedBookmakerProbability[], consensus: ThreeWayProbability, official: ThreeWayProbability, fallbackUsed: boolean): ExternalMarketQuality {
  const included = rows.filter(row => row.included), excluded = rows.filter(row => !row.included), staleCount = rows.filter(row => row.exclusionReason === "Stale odds").length;
  const averageOverround = included.length ? included.reduce((sum, row) => sum + row.overround, 0) / included.length : 0;
  const maxBookmakerDeviation = included.length ? Math.max(...included.map(row => calculateProbabilityDeviation(row.normalizedProbability, consensus).maxDeviation)) : 0;
  const officialMarketDeviation = calculateProbabilityDeviation(consensus, official), warnings: string[] = [];
  if (fallbackUsed) return {available: false, bookmakerCount: rows.length, includedBookmakerCount: 0, excludedBookmakerCount: excluded.length, averageOverround, maxBookmakerDeviation, officialMarketDeviation, staleCount, qualityScore: 0, qualityLevel: "UNAVAILABLE", warnings: ["外部市场不可用，已回退到官方SP去水概率"]};
  let score = 100;
  if (included.length === 1) score -= 35; else if (included.length === 2) score -= 20; else if (included.length === 3) score -= 10;
  if (included.length < 2) warnings.push("外部博彩公司数量不足");
  if (averageOverround > .18) score -= 30; else if (averageOverround > .12) score -= 15;
  if (averageOverround > .12) warnings.push("外部市场赔率水位偏高");
  score -= Math.min(20, staleCount * 5); if (staleCount) warnings.push("外部市场存在过期赔率");
  score -= Math.min(20, excluded.length * 5); if (excluded.length) warnings.push("部分博彩公司赔率异常已剔除");
  if (maxBookmakerDeviation > .12) score -= 20; else if (maxBookmakerDeviation > .08) score -= 10;
  if (officialMarketDeviation.maxDeviation > .18) score -= 35; else if (officialMarketDeviation.maxDeviation > .12) score -= 20; else if (officialMarketDeviation.maxDeviation > .08) score -= 10;
  if (officialMarketDeviation.maxDeviation > .08) warnings.push("外部市场与官方SP去水概率偏离较大");
  score = Math.max(0, Math.min(100, score));
  return {available: true, bookmakerCount: rows.length, includedBookmakerCount: included.length, excludedBookmakerCount: excluded.length, averageOverround, maxBookmakerDeviation, officialMarketDeviation, staleCount, qualityScore: score, qualityLevel: score >= 80 ? "HIGH" : score >= 60 ? "MEDIUM" : score > 0 ? "LOW" : "UNAVAILABLE", warnings};
}

export function calculateExternalMarketConsensus(bookmakers: ExternalBookmakerOdds[] | undefined, official: ThreeWayProbability, options: {maxOverround?: number; maxAgeMinutes?: number; maxDeviationFromMedian?: number; now?: number} = {}): ExternalMarketConsensus {
  if (!bookmakers?.length) {
    const quality = calculateExternalMarketQuality([], official, official, true);
    const warnings = ["外部市场赔率缺失，已使用官方SP去水概率作为fallback。", ...quality.warnings];
    return {probability: official, fairOdds: fairOddsFromProbability(official), normalizedBookmakers: [], quality: {...quality, warnings}, warnings, fallbackUsed: true, fallbackReason: "External market odds missing"};
  }
  const normalized = bookmakers.map(book => convertBookmakerOddsToProbability(book, options));
  const filtered = detectOutlierBookmakers(normalized, options);
  const consensus = calculateWeightedConsensusProbability(filtered, official);
  const quality = calculateExternalMarketQuality(filtered, consensus.probability, official, consensus.fallbackUsed);
  const warnings = [...quality.warnings];
  return {probability: consensus.probability, fairOdds: fairOddsFromProbability(consensus.probability), normalizedBookmakers: filtered, quality: {...quality, warnings}, warnings, fallbackUsed: consensus.fallbackUsed, fallbackReason: consensus.fallbackReason};
}
