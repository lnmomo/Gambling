import type {BacktestRecord, CalibrationBucket} from "../types";

export function buildCalibrationTable(records: BacktestRecord[], options: {bucketSize?: number; useSelectedOnly?: boolean} = {}): CalibrationBucket[] {
  const size = Math.min(1, Math.max(.01, options.bucketSize ?? .05));
  const observations = records.flatMap(record => {
    if (!record.actualResult || record.recommendation === "NO_BET") return [];
    if (options.useSelectedOnly !== false) return record.selectedProbability === undefined || record.hit === null ? [] : [{probability: record.selectedProbability, hit: record.hit ? 1 : 0}];
    const resultKey = record.actualResult === "HOME" ? "home" : record.actualResult === "DRAW" ? "draw" : "away";
    return [{probability: record.prediction.finalProbability[resultKey], hit: 1}];
  });
  const bucketCount = Math.ceil(1 / size), table: CalibrationBucket[] = [];
  for (let index = 0; index < bucketCount; index++) { const lowerBound = index * size, upperBound = Math.min(1, lowerBound + size), rows = observations.filter(row => row.probability >= lowerBound && (index === bucketCount - 1 ? row.probability <= upperBound : row.probability < upperBound)); if (!rows.length) continue; const avgPredictedProbability = rows.reduce((sum, row) => sum + row.probability, 0) / rows.length, actualHitRate = rows.reduce((sum, row) => sum + row.hit, 0) / rows.length; table.push({bucket: `${Math.round(lowerBound * 100)}%-${Math.round(upperBound * 100)}%`, lowerBound, upperBound, count: rows.length, avgPredictedProbability, actualHitRate, calibrationError: Math.abs(avgPredictedProbability - actualHitRate)}); }
  return table;
}
export function calculateExpectedCalibrationError(table: CalibrationBucket[]) { const total = table.reduce((sum, row) => sum + row.count, 0); return total ? table.reduce((sum, row) => sum + row.count / total * row.calibrationError, 0) : 0; }
