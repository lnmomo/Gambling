import {useMemo, useState} from "react";
import PageHeader from "../components/PageHeader";
import BacktestSummaryCards from "../components/BacktestSummaryCards";
import CalibrationTable from "../components/CalibrationTable";
import ClvPanel from "../components/ClvPanel";
import ErrorAnalysisPanel from "../components/ErrorAnalysisPanel";
import BacktestRecordsTable from "../components/BacktestRecordsTable";
import StackingComparisonPanel from "../components/StackingComparisonPanel";
import {calculateBacktestMetrics} from "../algorithm/backtestMetrics";
import {buildCalibrationTable} from "../algorithm/calibrationAnalysis";
import {analyzePredictionErrors} from "../algorithm/errorAnalysis";
import {demoBacktestResult, demoStackingEvaluation} from "../data/backtestData";
import {stackingMockModel} from "../data/stackingMockModel";

export default function BacktestPage() {
  const records = demoBacktestResult.records;
  const [league, setLeague] = useState("ALL"), [includeNoBet, setIncludeNoBet] = useState(true);
  const filtered = useMemo(() => records.filter(record => (league === "ALL" || record.league === league) && (includeNoBet || record.recommendation !== "NO_BET")), [records, league, includeNoBet]);
  const metrics = useMemo(() => calculateBacktestMetrics(filtered), [filtered]);
  const calibration = useMemo(() => buildCalibrationTable(filtered, {useSelectedOnly: true}), [filtered]);
  const analysis = useMemo(() => analyzePredictionErrors(filtered), [filtered]);
  return <div className="page"><PageHeader title="回测与校准诊断" subtitle="严格按时间 walk-forward，联合评估概率质量、ROI、CLV 与 Stacking 候选模型"/><section className="panel"><div className="filter-bar"><select value={league} onChange={event => setLeague(event.target.value)}><option value="ALL">全部联赛</option>{[...new Set(records.map(record => record.league))].map(value => <option key={value}>{value}</option>)}</select><label><input type="checkbox" checked={includeNoBet} onChange={event => setIncludeNoBet(event.target.checked)}/> 包含 NO_BET</label></div></section><BacktestSummaryCards metrics={metrics}/><StackingComparisonPanel evaluation={demoStackingEvaluation} model={stackingMockModel}/><CalibrationTable rows={calibration}/><ClvPanel records={filtered}/><ErrorAnalysisPanel report={analysis}/><BacktestRecordsTable records={filtered}/></div>;
}
