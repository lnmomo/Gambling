import type {MarketMovementSignal} from "../types";
export default function MarketMovementAlertPanel({signals}: {signals: MarketMovementSignal[]}) { return <div>{signals.length ? signals.map((signal, index) => <p key={`${signal.type}-${index}`}><b>{signal.severity} · {signal.type}</b>：{signal.description}，建议 {signal.recommendedAction}</p>) : <p>暂无达到阈值的市场变动。</p>}</div>; }
