export const AlgorithmConfig = {
  poisson: {halfLife: 90, minLambdaHome: .25, maxLambdaHome: 4, minLambdaAway: .20, maxLambdaAway: 3.5, minTeamMatches: 10, fullReliabilityMatches: 20},
  dixonColes: {defaultRho: -.10, minRho: -.18, maxRho: .02, maxGoals: 10},
  elo: {initialElo: 1500, homeAdvantage: 65, kLeague: 20, kCup: 25, kFriendly: 10},
  ensemble: {noMl: {market: .45, dixonColes: .35, elo: .20}, withMl: {market: .35, dixonColes: .30, elo: .15, ml: .20}},
  calibration: {method: "temperature" as const, defaultTemperature: 1.08},
  marketGuard: {anchorDeviation: .12, noBetDeviation: .18, anchorStrength: .50},
  critic: {baseEvThreshold: .045, maxDailyRecommendations: 5, minRecommendedOdds: 1.25, maxAllowedProbability: .88, highProbabilityWarning: .82},
  bankroll: {fractionalKelly: .25, maxSingleStakeRatio: .01},
};

export const teamAliasMap: Record<string, string> = {
  "曼城": "Manchester City", "曼彻斯特城": "Manchester City", "man city": "Manchester City", "manchester city fc": "Manchester City",
  "热刺": "Tottenham Hotspur", "tottenham": "Tottenham Hotspur", "spurs": "Tottenham Hotspur",
  "皇马": "Real Madrid", "皇家马德里": "Real Madrid", "real madrid cf": "Real Madrid",
};
