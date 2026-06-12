import {Link} from "react-router-dom";
import type {OfficialMatch} from "../types";
import EmptyState from "./EmptyState";
import StatusTag from "./StatusTag";

const pick=(m:OfficialMatch)=>m.recommendation==="HOME"?m.ev.home:m.recommendation==="DRAW"?m.ev.draw:m.recommendation==="AWAY"?m.ev.away:Math.max(...Object.values(m.ev));
const triple=(values:{home:number;draw:number;away:number})=>`${values.home.toFixed(2)} / ${values.draw.toFixed(2)} / ${values.away.toFixed(2)}`;

export default function MatchTable({matches}:{matches:OfficialMatch[]}){
  if(!matches.length)return <EmptyState/>;
  return <div className="table-scroll"><table className="data-table"><thead><tr><th>比赛ID</th><th>联赛</th><th>主队 vs 客队</th><th>开赛时间</th><th>官方SP</th><th>模型概率</th><th>模型公平赔率</th><th>EV</th><th>状态</th><th>操作</th></tr></thead><tbody>{matches.map(m=>{const hasSp=Object.values(m.officialSp).every(Boolean);const hasPrediction=Object.values(m.modelProbability).some(Boolean);return <tr key={m.id}><td><code>{m.officialMatchId}</code></td><td><span className="league-tag">{m.league}</span></td><td><b>{m.homeTeam} <em>vs</em> {m.awayTeam}</b></td><td>{new Date(m.kickoffTime).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"})}</td><td>{hasSp?triple(m.officialSp):"-"}</td><td>{hasPrediction?`${(m.modelProbability.home*100).toFixed(1)}% / ${(m.modelProbability.draw*100).toFixed(1)}% / ${(m.modelProbability.away*100).toFixed(1)}%`:"暂无"}</td><td>{hasPrediction?triple(m.modelFairOdds):"暂无"}</td><td className={m.marketCalibrated?(pick(m)>=0?"positive":"negative"):""}>{m.marketCalibrated?`${pick(m)>=0?"+":""}${(pick(m)*100).toFixed(2)}%`:"待市场校准"}</td><td><StatusTag status={m.status}/></td><td><Link className="table-action" to={`/matches/${m.id}`}>查看详情</Link></td></tr>})}</tbody></table></div>;
}
