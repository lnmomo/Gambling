import type { LucideIcon } from "lucide-react";

export default function MetricCard({title,value,note,icon:Icon,tone="green"}:{title:string;value:string;note:string;icon:LucideIcon;tone?:string}) {
  return <article className="metric-card"><div><span>{title}</span><strong className={tone}>{value}</strong><small>{note}</small></div><i className={`metric-icon ${tone}`}><Icon size={20}/></i></article>
}
