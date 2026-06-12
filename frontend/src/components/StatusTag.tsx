import type {MatchStatus} from "../types";
const labels:Record<MatchStatus,string>={NOT_STARTED:"未开赛",LIVE:"进行中",FINISHED:"已结束",CANCELLED:"已取消",POSTPONED:"已延期",CLOSED:"已停售"};
export default function StatusTag({status}:{status:MatchStatus}){return <span className={`status-tag status-${status.toLowerCase()}`}>{labels[status]}</span>}
