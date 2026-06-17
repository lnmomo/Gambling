import type {TrueOddsOptimizationResult} from "../types";

const pct=(value?:number|null)=>value===undefined||value===null||!Number.isFinite(value)?"-":`${(value*100).toFixed(2)}%`;

export default function EdgeQualityOptimizerPanel({result}:{result:TrueOddsOptimizationResult}) {
  const best=result.ranking[0];
  const rows=[["Recommendations","recommendation_count"],["ROI","roi"],["Avg CLV","average_clv"],["Positive CLV","positive_clv_rate"],["Max Drawdown","max_drawdown"],["No Bet Ratio","no_bet_ratio"],["Log Loss","log_loss"],["Brier","brier_score"]] as const;
  return <section className="panel">
    <div className="panel-heading"><div><h2>Edge Quality Optimizer</h2><p>优化器只用于选择 True Odds Filter 参数，不代表保证盈利。生产启用前仍需长期真实 CLV 验证。</p></div><span className={`recommend-badge ${result.recommendedForProduction?"":"no-bet"}`}>{result.promotionDecision}</span></div>
    <section className="summary-strip" style={{padding:16,margin:0}}>
      <span>Configs Tested<b>{result.variantResults.length}</b></span><span>Best Config<b>{result.bestConfig?.name??"-"}</b></span><span>Recommended<b>{result.recommendedForProduction?"YES":"NO"}</b></span><span>Blocked<b>{result.blockedAnalysis.blockedCount}</b></span>
    </section>
    <div className="table-scroll"><table className="data-table"><thead><tr><th>Metric</th><th>Baseline</th><th>Best Config</th></tr></thead><tbody>{rows.map(([label,key])=><tr key={key}><td>{label}</td><td>{key.includes("count")?result.baselineMetrics[key]:pct(result.baselineMetrics[key])}</td><td>{best?(key.includes("count")?best.metrics[key]:pct(best.metrics[key])):"-"}</td></tr>)}</tbody></table></div>
    <div className="two-column backtest-inner"><div><h3>Blocked Recommendation Analysis</h3>{result.blockedAnalysis.summary.map(line=><p key={line}>{line}</p>)}<p>Estimated loss avoided: {result.blockedAnalysis.estimatedLossAvoided?.toFixed(2)??"-"}</p></div><div><h3>Top Config Ranking</h3>{result.ranking.slice(0,5).map(row=><p key={row.variantId}><b>{row.name}</b> score {row.score.toFixed(2)} · ROI {pct(row.metrics.roi)} · CLV {pct(row.metrics.average_clv)}</p>)}</div></div>
    <h3 className="tab-content">Bucket Performance</h3><div className="table-scroll"><table className="data-table"><thead><tr><th>Type</th><th>Bucket</th><th>Sample</th><th>ROI</th><th>CLV</th><th>Positive CLV</th><th>Warnings</th></tr></thead><tbody>{result.bucketPerformance.slice(0,12).map(row=><tr key={`${row.bucketType}-${row.bucketName}`}><td>{row.bucketType}</td><td>{row.bucketName}</td><td>{row.sampleCount}</td><td>{pct(row.roi)}</td><td>{pct(row.averageClv)}</td><td>{pct(row.positiveClvRate)}</td><td>{row.warnings.join("; ")||"-"}</td></tr>)}</tbody></table></div>
  </section>;
}
