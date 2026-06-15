import type {MatchPrediction} from "../types";
import ModelVersionBadge from "./ModelVersionBadge";
import StackingFeatureImportanceTable from "./StackingFeatureImportanceTable";
const pct = (value?: number) => value === undefined || !Number.isFinite(value) ? "-" : `${(value * 100).toFixed(1)}%`;
export default function StackingModelPanel({prediction}: {prediction: MatchPrediction}) {
  const stacking = prediction.stackingPrediction;
  return <section className="panel tabs-panel"><div className="panel-heading"><div><h2>Stacking 融合解释</h2><p>Stacking 学习如何融合市场、外部共识、纯模型、质量和风险特征；输出仍需经过校准、市场锚定、EV 与 Critic。</p></div><ModelVersionBadge source={prediction.probabilitySource} version={prediction.modelVersion}/></div><div className="summary-strip" style={{padding:16,margin:0}}><span>主胜<b>{pct(prediction.stackedProbability?.home)}</b></span><span>平局<b>{pct(prediction.stackedProbability?.draw)}</b></span><span>客胜<b>{pct(prediction.stackedProbability?.away)}</b></span><span>区分度<b>{pct(stacking?.confidence)}</b></span><span>Fallback<b>{stacking?.fallbackUsed ? "是" : "否"}</b></span></div>{stacking?.fallbackReason && <p className="tab-content">{stacking.fallbackReason}</p>}<StackingFeatureImportanceTable features={stacking?.topFeatures}/></section>;
}
