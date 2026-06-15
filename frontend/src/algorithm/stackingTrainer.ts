import type {BacktestInputMatch, HistoricalMatch, StackingTrainingExample} from "../types";
import {calculateMatchPrediction} from "./probabilityEngine";
import {buildStackingFeatureVector} from "./stackingFeatureBuilder";
import {trainMultinomialLogisticRegression, predictWithStackingModel} from "./stackingModel";
import {evaluateStackingCalibration} from "./stackingCalibration";
import {getPastMatchesOnly, splitMatchesByTime, sortMatchesByTime} from "./timeSplit";

export function buildStackingTrainingExamples(inputMatches: BacktestInputMatch[], historicalMatches: HistoricalMatch[], options: {halfLifeDays?: number; minDataQualityScore?: number} = {}): StackingTrainingExample[] {
  const completed = sortMatchesByTime(inputMatches).filter(match => match.result?.result), latest = completed.reduce((max, match) => Math.max(max, Date.parse(match.kickoffTime)), 0), halfLifeDays = options.halfLifeDays ?? 365;
  return completed.flatMap(match => {
    const prediction = calculateMatchPrediction({...match, status: "FINISHED", marketOdds: {home: 0, draw: 0, away: 0}, updatedAt: match.kickoffTime}, getPastMatchesOnly(historicalMatches, match.kickoffTime), match.context ?? {}, 10_000, {useStacking: false});
    const qualityScore = prediction.externalMarketQuality.qualityScore;
    if (!prediction.probabilityAvailable || qualityScore < (options.minDataQualityScore ?? 0)) return [];
    const ageDays = Math.max(0, (latest - Date.parse(match.kickoffTime)) / 86_400_000), timeWeight = Math.exp(-ageDays / halfLifeDays), qualityWeight = .5 + .5 * Math.min(1, Math.max(0, qualityScore / 100));
    return [{features: buildStackingFeatureVector(match, prediction), label: match.result!.result, sampleWeight: timeWeight * qualityWeight}];
  });
}

export function trainStackingModelWithTimeSplit(inputMatches: BacktestInputMatch[], historicalMatches: HistoricalMatch[], options: {trainRatio?: number; validationRatio?: number; testRatio?: number; minTrainExamples?: number} = {}) {
  const examples = buildStackingTrainingExamples(inputMatches, historicalMatches), split = splitMatchesByTime(examples.map(example => ({...example, kickoffTime: example.features.kickoffTime})), options), minTrainExamples = options.minTrainExamples ?? 200;
  const result = {trainExamples: split.train as StackingTrainingExample[], validationExamples: split.validation as StackingTrainingExample[], testExamples: split.test as StackingTrainingExample[], warnings: [] as string[], coefficients: undefined as ReturnType<typeof trainMultinomialLogisticRegression> | undefined};
  if (result.trainExamples.length < minTrainExamples || result.trainExamples.length < 200) { result.warnings.push("训练样本不足，Stacking 模型未启用。"); return result; }
  const coefficients = trainMultinomialLogisticRegression(result.trainExamples), validationRows = result.validationExamples.map(example => ({probability: predictWithStackingModel(example.features, coefficients).probability, label: example.label})), validation = evaluateStackingCalibration(validationRows);
  coefficients.validationMatchCount = result.validationExamples.length; coefficients.metrics.validationLogLoss = validation.logLoss; coefficients.metrics.validationBrierScore = validation.brierScore; coefficients.metrics.validationCalibrationError = validation.calibrationError; result.coefficients = coefficients;
  return result;
}
