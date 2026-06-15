import type {EnhancedHistoricalMatch, TeamHomeAwayStrength} from "../types";
import {normalizeTeamName} from "./teamNameNormalizer";
const clamp=(v:number,a:number,b:number)=>Math.min(b,Math.max(a,v));
export function calculateTeamHomeAwayStrength(matches:EnhancedHistoricalMatch[],teamName:string,options:{league?:string;cutoffTime?:string;halfLife?:number;minFullReliabilityMatches?:number;useXgIfAvailable?:boolean}={}):TeamHomeAwayStrength{
 const team=normalizeTeamName(teamName),cutoff=options.cutoffTime?Date.parse(options.cutoffTime):Date.now(),halfLife=options.halfLife??90,full=options.minFullReliabilityMatches??20,useXg=options.useXgIfAvailable!==false;
 const eligible=matches.filter(m=>Date.parse(m.playedAt)<cutoff&&[normalizeTeamName(m.homeTeam),normalizeTeamName(m.awayTeam)].includes(team));
 const leagueRows=matches.filter(m=>Date.parse(m.playedAt)<cutoff&&(!options.league||m.league===options.league)), count=leagueRows.length||1;
 const avgH=leagueRows.reduce((s,m)=>s+(useXg&&m.homeXg!==undefined?m.homeXg:m.homeGoals),0)/count||1.45,avgA=leagueRows.reduce((s,m)=>s+(useXg&&m.awayXg!==undefined?m.awayXg:m.awayGoals),0)/count||1.15,avg=(avgH+avgA)/2;
 let hf=0,ha=0,hw=0,af=0,aa=0,aw=0;
 for(const m of eligible){const home=normalizeTeamName(m.homeTeam)===team,w=Math.exp(-Math.max(0,(cutoff-Date.parse(m.playedAt))/86400000)/halfLife)*(options.league&&m.league!==options.league?.5:1),forValue=home?(useXg&&m.homeXg!==undefined?m.homeXg:m.homeGoals):(useXg&&m.awayXg!==undefined?m.awayXg:m.awayGoals),against=home?(useXg&&m.awayXg!==undefined?m.awayXg:m.awayGoals):(useXg&&m.homeXg!==undefined?m.homeXg:m.homeGoals);if(home){hf+=forValue*w;ha+=against*w;hw+=w}else{af+=forValue*w;aa+=against*w;aw+=w}}
 const relH=Math.min(1,hw/full),relA=Math.min(1,aw/full),total=hw+aw,rel=Math.min(1,total/(full*2)),overallAttack=1+(((hf+af)/(total||1)/avg)-1)*rel,overallDefense=1+(((ha+aa)/(total||1)/avg)-1)*rel,warnings:string[]=[];
 if(hw<3)warnings.push("主场样本不足，主场强度已向整体水平收缩。");if(aw<3)warnings.push("客场样本不足，客场强度已向整体水平收缩。");if(!total)warnings.push("球队没有可用历史样本，使用中性强度。");
 const shrink=(raw:number,r:number,fallback:number)=>clamp(1+(raw-1)*r+(fallback-1)*(1-r)*.5,.55,1.8);
 return{team:teamName,homeAttackStrength:shrink(hw?hf/hw/avgH:overallAttack,relH,overallAttack),homeDefenseWeakness:shrink(hw?ha/hw/avgA:overallDefense,relH,overallDefense),awayAttackStrength:shrink(aw?af/aw/avgA:overallAttack,relA,overallAttack),awayDefenseWeakness:shrink(aw?aa/aw/avgH:overallDefense,relA,overallDefense),overallAttackStrength:clamp(overallAttack,.55,1.8),overallDefenseWeakness:clamp(overallDefense,.55,1.8),homeWeightedMatches:hw,awayWeightedMatches:aw,totalWeightedMatches:total,homeReliability:relH,awayReliability:relA,overallReliability:rel,warnings};
}
