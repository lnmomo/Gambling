import { Inbox } from "lucide-react";
export default function EmptyState({title="暂无官方比赛数据",description="当前没有符合条件的数据"}:{title?:string;description?:string}){return <div className="empty-state"><Inbox size={30}/><b>{title}</b><p>{description}</p></div>}
