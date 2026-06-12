import type {ReactNode} from "react";
export default function PageHeader({title,subtitle,actions}:{title:string;subtitle:string;actions?:ReactNode}){return <div className="page-heading"><div><p>工作台 / {title}</p><h1>{title}</h1><span>{subtitle}</span></div>{actions}</div>}
