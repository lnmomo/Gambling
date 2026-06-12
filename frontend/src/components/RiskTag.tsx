import type {RiskLevel} from "../types";
export default function RiskTag({level}:{level:RiskLevel}){return <span className={`risk-tag ${level.toLowerCase()}`}>{{LOW:"低风险",MEDIUM:"中风险",HIGH:"高风险"}[level]}</span>}
