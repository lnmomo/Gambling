import type {MatchPrediction} from "../types";
import {calculatePortfolioExposure} from "../algorithm/portfolioRisk";
import {getBankrollConfig} from "./bankrollService";
export const getPortfolioExposure=(predictions:MatchPrediction[],date=new Date().toISOString().slice(0,10))=>calculatePortfolioExposure(predictions,getBankrollConfig().currentBankroll,date);
