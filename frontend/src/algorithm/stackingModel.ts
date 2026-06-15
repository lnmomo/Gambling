import type {StackingFeatureVector, StackingModelCoefficients, StackingPredictionOutput, StackingTrainingExample, ThreeWayProbability} from "../types";
import {DEFAULT_STACKING_FEATURE_NAMES, extractFeatureArray} from "./stackingFeatureBuilder";

export function softmax(scores: number[]): number[] {
  if (!scores.length || scores.some(score => !Number.isFinite(score))) return scores.map(() => 1 / Math.max(1, scores.length));
  const max = Math.max(...scores), exps = scores.map(score => Math.exp(Math.max(-700, score - max))), total = exps.reduce((sum, value) => sum + value, 0);
  return total > 0 && Number.isFinite(total) ? exps.map(value => value / total) : scores.map(() => 1 / scores.length);
}
const fallbackProbability = (vector: StackingFeatureVector): ThreeWayProbability => {
  const values = {home: vector.pureHomeProb, draw: vector.pureDrawProb, away: vector.pureAwayProb}, total = values.home + values.draw + values.away;
  return total > 0 && Object.values(values).every(Number.isFinite) ? {home: values.home / total, draw: values.draw / total, away: values.away / total} : {home: 1 / 3, draw: 1 / 3, away: 1 / 3};
};
const dot = (a: number[], b: number[]) => a.reduce((sum, value, index) => sum + value * (b[index] ?? 0), 0);

export function predictWithStackingModel(vector: StackingFeatureVector, coefficients?: StackingModelCoefficients): StackingPredictionOutput {
  if (!coefficients || coefficients.featureNames.length === 0) return {available: false, probability: fallbackProbability(vector), rawScores: {home: 0, draw: 0, away: 0}, confidence: 0, fallbackUsed: true, fallbackReason: "Stacking model coefficients missing", warnings: ["Stacking 模型不可用，已回退到规则融合。"]};
  const raw = extractFeatureArray(vector, coefficients.featureNames), features = raw.map((value, index) => coefficients.featureStds?.[index] ? (value - (coefficients.featureMeans?.[index] ?? 0)) / coefficients.featureStds[index] : value);
  const scores = {home: dot(features, coefficients.homeWeights) + coefficients.homeBias, draw: dot(features, coefficients.drawWeights) + coefficients.drawBias, away: dot(features, coefficients.awayWeights) + coefficients.awayBias};
  const probabilities = softmax([scores.home, scores.draw, scores.away]), probability = {home: probabilities[0], draw: probabilities[1], away: probabilities[2]};
  const ordered = [...probabilities].sort((a, b) => b - a), classWeights = probabilities.indexOf(ordered[0]) === 0 ? coefficients.homeWeights : probabilities.indexOf(ordered[0]) === 1 ? coefficients.drawWeights : coefficients.awayWeights;
  const topFeatures = coefficients.featureNames.map((feature, index) => ({feature, contribution: features[index] * (classWeights[index] ?? 0)})).sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution)).slice(0, 8);
  return {available: true, probability, rawScores: scores, confidence: ordered[0] - ordered[1], modelVersion: coefficients.version, fallbackUsed: false, topFeatures, warnings: []};
}

export function trainMultinomialLogisticRegression(examples: StackingTrainingExample[], options: {featureNames?: string[]; learningRate?: number; epochs?: number; l2?: number} = {}): StackingModelCoefficients {
  if (examples.length < 200) throw new Error("Not enough training examples for stacking model");
  const featureNames = options.featureNames ?? [...DEFAULT_STACKING_FEATURE_NAMES], rows = examples.map(example => extractFeatureArray(example.features, featureNames));
  const means = featureNames.map((_, index) => rows.reduce((sum, row) => sum + row[index], 0) / rows.length), stds = featureNames.map((_, index) => Math.max(1e-6, Math.sqrt(rows.reduce((sum, row) => sum + (row[index] - means[index]) ** 2, 0) / rows.length)));
  const x = rows.map(row => row.map((value, index) => (value - means[index]) / stds[index])), weights = [featureNames.map(() => 0), featureNames.map(() => 0), featureNames.map(() => 0)], biases = [0, 0, 0];
  const lr = options.learningRate ?? .03, l2 = options.l2 ?? .001, epochs = options.epochs ?? 300, labels = {HOME: 0, DRAW: 1, AWAY: 2} as const, totalWeight = examples.reduce((sum, example) => sum + Math.max(0, example.sampleWeight), 0) || examples.length;
  for (let epoch = 0; epoch < epochs; epoch += 1) {
    const gradients = weights.map(row => row.map(() => 0)), biasGradients = [0, 0, 0];
    x.forEach((row, rowIndex) => { const probabilities = softmax(weights.map((classWeights, classIndex) => dot(row, classWeights) + biases[classIndex])), label = labels[examples[rowIndex].label], sampleWeight = Math.max(0, examples[rowIndex].sampleWeight) || 1; for (let c = 0; c < 3; c += 1) { const error = (probabilities[c] - (c === label ? 1 : 0)) * sampleWeight; biasGradients[c] += error; for (let f = 0; f < row.length; f += 1) gradients[c][f] += error * row[f]; } });
    for (let c = 0; c < 3; c += 1) { biases[c] -= lr * biasGradients[c] / totalWeight; for (let f = 0; f < featureNames.length; f += 1) weights[c][f] -= lr * (gradients[c][f] / totalWeight + l2 * weights[c][f]); }
  }
  const trainLogLoss = examples.reduce((sum, example, index) => { const probabilities = softmax(weights.map((classWeights, c) => dot(x[index], classWeights) + biases[c])), p = probabilities[labels[example.label]]; return sum - Math.log(Math.max(1e-12, p)); }, 0) / examples.length;
  return {modelType: "MULTINOMIAL_LOGISTIC_REGRESSION", featureNames, homeWeights: weights[0], drawWeights: weights[1], awayWeights: weights[2], homeBias: biases[0], drawBias: biases[1], awayBias: biases[2], featureMeans: means, featureStds: stds, trainedAt: new Date().toISOString(), trainingMatchCount: examples.length, validationMatchCount: 0, metrics: {trainLogLoss, validationLogLoss: 0, validationBrierScore: 0, validationCalibrationError: 0}, version: `stacking-${examples.length}-v1`};
}
