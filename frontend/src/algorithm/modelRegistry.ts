import type {StackingModelCoefficients} from "../types";
import {stackingMockModel} from "../data/stackingMockModel";

export interface StackingModelRegistration {status: "CANDIDATE" | "ENABLED" | "DISABLED"; coefficients?: StackingModelCoefficients; recommended: boolean; note: string}
const registry: StackingModelRegistration = {status: "CANDIDATE", coefficients: stackingMockModel, recommended: false, note: "候选模型仅用于本地时间切分回测；验证优于基线前不得设为生产默认。"};
export const getStackingModelRegistration = (): StackingModelRegistration => registry;
export const getCandidateStackingCoefficients = () => registry.coefficients;
