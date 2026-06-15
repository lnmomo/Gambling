import type {RecommendationLifecycleStatus} from "../types";
export default function RecommendationStatusBadge({status}: {status: RecommendationLifecycleStatus}) { return <span className={`recommend-badge ${status === "ACTIVE" ? "" : "no-bet"}`}>{status}</span>; }
