import type {StackingModelCoefficients} from "../types";
import {DEFAULT_STACKING_FEATURE_NAMES} from "../algorithm/stackingFeatureBuilder";

const weightsFor = (side: "Home" | "Draw" | "Away") => DEFAULT_STACKING_FEATURE_NAMES.map(name => {
  if (name === `market${side}Prob`) return .75;
  if (name === `external${side}Prob`) return .60;
  if (name === `pure${side}Prob`) return 1.10;
  if (name === `dixon${side}Prob` || name === `elo${side}Prob` || name === `glicko${side}Prob` || name === `xg${side}Prob`) return .20;
  if (name === "maxMarketPureDeviation" || name === "maxSubModelDeviation") return -.10;
  return 0;
});
export const stackingMockModel: StackingModelCoefficients = {modelType: "MULTINOMIAL_LOGISTIC_REGRESSION", featureNames: [...DEFAULT_STACKING_FEATURE_NAMES], homeWeights: weightsFor("Home"), drawWeights: weightsFor("Draw"), awayWeights: weightsFor("Away"), homeBias: 0, drawBias: 0, awayBias: 0, trainedAt: "2026-06-15T00:00:00.000Z", trainingMatchCount: 500, validationMatchCount: 100, metrics: {trainLogLoss: 1.02, validationLogLoss: 1.05, validationBrierScore: .218, validationCalibrationError: .061}, version: "stacking-candidate-v1"};
