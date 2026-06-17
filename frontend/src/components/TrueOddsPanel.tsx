import type {MatchPrediction} from "../types";

const pct = (value?: number | null) => value === undefined || value === null || !Number.isFinite(value) ? "-" : `${(value * 100).toFixed(2)}%`;
const odds = (value?: number | null) => value === undefined || value === null || !Number.isFinite(value) ? "-" : value.toFixed(2);

export default function TrueOddsPanel({prediction}: {prediction: MatchPrediction}) {
  const estimate = prediction.trueOddsEstimate;
  if (!estimate) return null;
  return <section className="panel tabs-panel">
    <div className="panel-heading">
      <div>
        <h2>True Odds Analysis</h2>
        <p>True Odds Engine 用于识别更可靠的 edge。它不会保证盈利，只用于减少模型噪声和假正期望。</p>
      </div>
      <span className={`recommend-badge ${estimate.selectedEdge.passesTrueOddsFilter ? "" : "no-bet"}`}>
        {estimate.selectedEdge.edgeQualityLevel}
      </span>
    </div>
    <section className="summary-strip" style={{padding: 16, margin: 0}}>
      <span>Selected Edge<b>{estimate.selectedEdge.outcome}</b></span>
      <span>Edge Score<b>{estimate.selectedEdge.edgeQualityScore.toFixed(0)}</b></span>
      <span>LowerBoundEV<b>{pct(estimate.selectedEdge.lowerBoundEv)}</b></span>
      <span>Adaptive Threshold<b>{pct(estimate.selectedEdge.adaptiveThreshold)}</b></span>
      <span>Method Agreement<b>{pct(estimate.marketMultiDevig.methodAgreementScore)}</b></span>
      <span>Uncertainty<b>{pct(estimate.uncertainty.overallUncertainty)}</b></span>
    </section>
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr><th>Outcome</th><th>True Prob</th><th>True Fair Odds</th><th>Lower</th><th>Upper</th><th>Expected EV</th><th>Lower EV</th><th>Threshold</th><th>Quality</th><th>Pass</th></tr></thead>
        <tbody>{(["HOME","DRAW","AWAY"] as const).map(outcome => {
          const key = outcome === "HOME" ? "home" : outcome === "DRAW" ? "draw" : "away";
          const edge = estimate.edgeQualityByOutcome[outcome];
          return <tr key={outcome}>
            <td>{outcome}</td><td>{pct(estimate.trueProbabilityEstimate[key])}</td><td>{odds(estimate.trueFairOdds[key])}</td>
            <td>{pct(estimate.uncertainty.lower[key])}</td><td>{pct(estimate.uncertainty.upper[key])}</td>
            <td>{pct(edge.expectedEv)}</td><td>{pct(edge.lowerBoundEv)}</td><td>{pct(edge.adaptiveThreshold)}</td>
            <td>{edge.edgeQualityLevel} / {edge.edgeNoiseRisk}</td><td>{edge.passesTrueOddsFilter ? "YES" : "NO"}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr><th>Devig Method</th><th>Home</th><th>Draw</th><th>Away</th><th>Overround</th><th>Valid</th><th>Warnings</th></tr></thead>
        <tbody>{Object.values(estimate.marketMultiDevig.methods).map(row => <tr key={row.method}>
          <td>{row.method}{row.method === estimate.marketMultiDevig.recommendedMethod ? " *" : ""}</td>
          <td>{pct(row.probability.home)}</td><td>{pct(row.probability.draw)}</td><td>{pct(row.probability.away)}</td>
          <td>{pct(row.overround - 1)}</td><td>{row.valid ? "YES" : "NO"}</td><td>{row.warnings.join("; ") || "-"}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <div className="critic-list tab-content">
      {estimate.selectedEdge.reasons.map(reason => <div className="fail" key={reason}>{reason}</div>)}
      {estimate.warnings.map(warning => <div key={warning}>{warning}</div>)}
    </div>
  </section>;
}
