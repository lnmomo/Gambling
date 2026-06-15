import type {ExternalOddsSnapshot, OfficialSpSnapshot} from "../types";
const pct = (value: number) => `${(value * 100).toFixed(1)}%`;
export default function OddsMovementChart({official, external}: {official: OfficialSpSnapshot[]; external: ExternalOddsSnapshot[]}) {
  const rows = official.map((snapshot, index) => ({at: snapshot.capturedAt, official: snapshot.marketProbability, external: external[index]?.externalMarketProbability}));
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>时间</th><th>官方主/平/客</th><th>外部主/平/客</th></tr></thead><tbody>{rows.map(row => <tr key={row.at}><td>{new Date(row.at).toLocaleString("zh-CN")}</td><td>{Object.values(row.official).map(pct).join(" / ")}</td><td>{row.external ? Object.values(row.external).map(pct).join(" / ") : "-"}</td></tr>)}</tbody></table></div>;
}
