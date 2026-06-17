import {useMemo, useState} from "react";
import BacktestRecordsTable from "../components/BacktestRecordsTable";
import BacktestSummaryCards from "../components/BacktestSummaryCards";
import CalibrationTable from "../components/CalibrationTable";
import ClvPanel from "../components/ClvPanel";
import DrawdownWarningPanel from "../components/DrawdownWarningPanel";
import EdgeQualityOptimizerPanel from "../components/EdgeQualityOptimizerPanel";
import EquityCurvePanel from "../components/EquityCurvePanel";
import ErrorAnalysisPanel from "../components/ErrorAnalysisPanel";
import PageHeader from "../components/PageHeader";
import StakeBreakdownTable from "../components/StakeBreakdownTable";
import StackingComparisonPanel from "../components/StackingComparisonPanel";
import {calculateBacktestMetrics} from "../algorithm/backtestMetrics";
import {buildCalibrationTable} from "../algorithm/calibrationAnalysis";
import {runEdgeQualityOptimization} from "../algorithm/edgeQualityOptimizer";
import {analyzePredictionErrors} from "../algorithm/errorAnalysis";
import {demoBacktestResult, demoStackingEvaluation} from "../data/backtestData";
import {stackingMockModel} from "../data/stackingMockModel";

export default function BacktestPage() {
  const records = demoBacktestResult.records;
  const [league, setLeague] = useState("ALL");
  const [includeNoBet, setIncludeNoBet] = useState(true);
  const filtered = useMemo(
    () => records.filter(record => (league === "ALL" || record.league === league) && (includeNoBet || record.recommendation !== "NO_BET")),
    [records, league, includeNoBet],
  );
  const metrics = useMemo(() => calculateBacktestMetrics(filtered), [filtered]);
  const calibration = useMemo(() => buildCalibrationTable(filtered, {useSelectedOnly: true}), [filtered]);
  const analysis = useMemo(() => analyzePredictionErrors(filtered), [filtered]);
  const optimizer = useMemo(() => runEdgeQualityOptimization(filtered, undefined, {minSamples: 200}), [filtered]);

  return <div className="page">
    <PageHeader title="回测与资金曲线诊断" subtitle="Walk-forward 概率评估 + Risk Adjusted Kelly 动态 bankroll。" />
    <section className="panel">
      <div className="filter-bar">
        <select value={league} onChange={event => setLeague(event.target.value)}>
          <option value="ALL">全部联赛</option>
          {[...new Set(records.map(record => record.league))].map(value => <option key={value}>{value}</option>)}
        </select>
        <label><input type="checkbox" checked={includeNoBet} onChange={event => setIncludeNoBet(event.target.checked)} /> 包含 NO_BET</label>
      </div>
    </section>
    <BacktestSummaryCards metrics={metrics} />
    <EdgeQualityOptimizerPanel result={optimizer} />
    <div className="two-column">
      <EquityCurvePanel records={filtered} />
      <DrawdownWarningPanel drawdown={[...filtered].reverse().find(row => row.drawdownState)?.drawdownState} />
    </div>
    <StakeBreakdownTable records={filtered} />
    <StackingComparisonPanel evaluation={demoStackingEvaluation} model={stackingMockModel} />
    <CalibrationTable rows={calibration} />
    <ClvPanel records={filtered} />
    <ErrorAnalysisPanel report={analysis} />
    <BacktestRecordsTable records={filtered} />
  </div>;
}
