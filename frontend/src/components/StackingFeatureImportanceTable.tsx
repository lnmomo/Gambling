export default function StackingFeatureImportanceTable({features = []}: {features?: Array<{feature: string; contribution: number}>}) {
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>特征</th><th>贡献值</th><th>方向</th></tr></thead><tbody>{features.length ? features.map(row => <tr key={row.feature}><td>{row.feature}</td><td>{row.contribution.toFixed(4)}</td><td>{row.contribution >= 0 ? "支持" : "抑制"}</td></tr>) : <tr><td colSpan={3}>当前没有可用的 Stacking 特征贡献。</td></tr>}</tbody></table></div>;
}
