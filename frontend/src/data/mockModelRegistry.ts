import type {ModelGovernanceRecord} from "../types";

export const championModel: ModelGovernanceRecord = {
  modelId: "rule-ensemble-v5",
  modelName: "Rule-based probability ensemble",
  modelType: "RULE_BASED_ENSEMBLE",
  version: "5.0.0",
  role: "CHAMPION",
  createdAt: "2026-05-01T00:00:00.000Z",
  activatedAt: "2026-05-15T00:00:00.000Z",
  trainingMatchCount: 18_240,
  validationMatchCount: 2_280,
  testMatchCount: 1_120,
  metrics: {logLoss: 1.031, brierScore: .211, calibrationError: .041, roi: .018, averageClv: .006, positiveClvRate: .532},
  promotionStatus: "PROMOTED",
  warnings: [],
};

export const challengerModel: ModelGovernanceRecord = {
  modelId: "stacking-v1",
  modelName: "Stacking probability fusion",
  modelType: "STACKING_MODEL",
  version: "1.0.0-candidate",
  role: "CHALLENGER",
  createdAt: "2026-06-01T00:00:00.000Z",
  trainingMatchCount: 18_240,
  validationMatchCount: 2_280,
  testMatchCount: 180,
  metrics: {logLoss: 1.024, brierScore: .209, calibrationError: .044, roi: .012, averageClv: .004, positiveClvRate: .519},
  baselineModelId: championModel.modelId,
  promotionStatus: "CANDIDATE",
  promotionReason: "Awaiting sufficient out-of-sample matches and manual approval.",
  warnings: ["The challenger is not enabled for production predictions."],
};

export const modelRegistry = [championModel, challengerModel];
