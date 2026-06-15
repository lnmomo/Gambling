export default function ModelVersionBadge({version, source}: {version?: string; source?: string}) {
  return <span className={`recommend-badge ${source === "STACKING_FALLBACK" ? "no-bet" : ""}`}>{source ?? "RULE_BASED_ENSEMBLE"}{version ? ` · ${version}` : ""}</span>;
}
