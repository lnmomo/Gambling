import type {SystemHealth} from "../services/healthService";

export default function DataQualityPanel({health}:{health:SystemHealth}) {
  const quality = health.dataQuality ?? {invalidSnapshots:0, duplicateSkipped:0, staleSnapshots:0};
  return <section className="panel">
    <div className="panel-heading"><div><h2>Data Quality</h2><p>无效、重复和过期快照会被记录，不应进入 ACTIVE 推荐。</p></div></div>
    <section className="summary-strip" style={{padding:16,margin:0}}>
      <span>Invalid snapshots<b>{quality.invalidSnapshots}</b></span>
      <span>Duplicate skipped<b>{quality.duplicateSkipped}</b></span>
      <span>Stale snapshots<b>{quality.staleSnapshots}</b></span>
    </section>
  </section>;
}
