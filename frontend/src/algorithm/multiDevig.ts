import type {DevigMethod, DevigProbabilitySet, MultiDevigResult, ThreeWayOdds, ThreeWayProbability} from "../types";
import {normalizeProbability} from "./ensembleModel";

const methods:DevigMethod[]=["MULTIPLICATIVE","ADDITIVE","POWER","ODDS_RATIO","SHIN","CONSERVATIVE"];
const keys=["home","draw","away"] as const;
const validOdds=(odds:ThreeWayOdds)=>keys.every(key=>Number.isFinite(odds[key])&&odds[key]>1);
const fair=(p:ThreeWayProbability):ThreeWayOdds=>({home:1/Math.max(p.home,1e-12),draw:1/Math.max(p.draw,1e-12),away:1/Math.max(p.away,1e-12)});
const overround=(odds:ThreeWayOdds)=>keys.reduce((sum,key)=>sum+(odds[key]>1?1/odds[key]:0),0);
const invalid=(method:DevigMethod,odds:ThreeWayOdds,warnings:string[]):DevigProbabilitySet=>({method,probability:{home:0,draw:0,away:0},fairOdds:{home:0,draw:0,away:0},overround:overround(odds),valid:false,warnings});
const pack=(method:DevigMethod,odds:ThreeWayOdds,raw:ThreeWayProbability,warnings:string[]=[]):DevigProbabilitySet=>{
  if(!keys.every(key=>Number.isFinite(raw[key])&&raw[key]>0))return invalid(method,odds,["devig method produced invalid probabilities",...warnings]);
  const probability=normalizeProbability(raw);
  return {method,probability,fairOdds:fair(probability),overround:overround(odds),valid:true,warnings};
};
const bisect=(fn:(x:number)=>number,lo:number,hi:number,target=1)=>{
  let flo=fn(lo)-target,fhi=fn(hi)-target;if(!Number.isFinite(flo)||!Number.isFinite(fhi)||flo*fhi>0)return undefined;
  for(let i=0;i<80;i++){const mid=(lo+hi)/2,fmid=fn(mid)-target;if(Math.abs(fmid)<1e-12)return mid;if(flo*fmid<=0){hi=mid;fhi=fmid}else{lo=mid;flo=fmid}}
  return (lo+hi)/2;
};
export function calculateMultiDevigProbabilities(odds:ThreeWayOdds,options:{source?:string;recommendedMethod?:DevigMethod}={}):MultiDevigResult{
  const source=options.source??"market",clean={home:Number(odds.home),draw:Number(odds.draw),away:Number(odds.away)};
  if(!validOdds(clean)){const neutral={home:1/3,draw:1/3,away:1/3};return{source,odds:clean,methods:Object.fromEntries(methods.map(method=>[method,invalid(method,clean,["odds must be finite and > 1"])])) as Record<DevigMethod,DevigProbabilitySet>,recommendedMethod:"MULTIPLICATIVE",recommendedProbability:neutral,recommendedFairOdds:fair(neutral),methodAgreementScore:0,methodSpread:{home:0,draw:0,away:0,max:0},warnings:["invalid odds"]}}
  const implied={home:1/clean.home,draw:1/clean.draw,away:1/clean.away};
  const multiplicative=pack("MULTIPLICATIVE",clean,implied);
  const excess=implied.home+implied.draw+implied.away-1,addRaw={home:implied.home-excess/3,draw:implied.draw-excess/3,away:implied.away-excess/3};
  const additive=keys.some(key=>addRaw[key]<=0)?{...multiplicative,method:"ADDITIVE" as DevigMethod,warnings:["additive invalid; used multiplicative fallback"]}:pack("ADDITIVE",clean,addRaw);
  const k=bisect(x=>keys.reduce((sum,key)=>sum+implied[key]**x,0),.5,2.5);
  const power=k===undefined?{...multiplicative,method:"POWER" as DevigMethod,warnings:["power solver failed; used multiplicative fallback"]}:pack("POWER",clean,{home:implied.home**k,draw:implied.draw**k,away:implied.away**k});
  const c=bisect(x=>keys.reduce((sum,key)=>sum+implied[key]/(x+implied[key]-x*implied[key]),0),.01,100);
  const oddsRatio=c===undefined?{...multiplicative,method:"ODDS_RATIO" as DevigMethod,warnings:["odds-ratio solver failed; used multiplicative fallback"]}:pack("ODDS_RATIO",clean,{home:implied.home/(c+implied.home-c*implied.home),draw:implied.draw/(c+implied.draw-c*implied.draw),away:implied.away/(c+implied.away-c*implied.away)});
  const shin=pack("SHIN",clean,{home:power.probability.home*.97+1/3*.03,draw:power.probability.draw*.97+1/3*.03,away:power.probability.away*.97+1/3*.03},["shin-like approximation used"]);
  const base=[multiplicative,additive,power,oddsRatio,shin].filter(row=>row.valid);
  const conservative=pack("CONSERVATIVE",clean,{home:Math.min(...base.map(row=>row.probability.home)),draw:Math.min(...base.map(row=>row.probability.draw)),away:Math.min(...base.map(row=>row.probability.away))},["conservative worst-case estimate"]);
  const resultMethods={MULTIPLICATIVE:multiplicative,ADDITIVE:additive,POWER:power,ODDS_RATIO:oddsRatio,SHIN:shin,CONSERVATIVE:conservative};
  const recommended=(options.recommendedMethod&&resultMethods[options.recommendedMethod]?.valid?options.recommendedMethod:power.valid?"POWER":"MULTIPLICATIVE") as DevigMethod;
  const valid=Object.values(resultMethods).filter(row=>row.valid),spread={home:0,draw:0,away:0,max:0};
  keys.forEach(key=>{spread[key]=Math.max(...valid.map(row=>row.probability[key]))-Math.min(...valid.map(row=>row.probability[key]))});spread.max=Math.max(spread.home,spread.draw,spread.away);
  return{source,odds:clean,methods:resultMethods,recommendedMethod:recommended,recommendedProbability:resultMethods[recommended].probability,recommendedFairOdds:resultMethods[recommended].fairOdds,methodAgreementScore:Math.max(0,Math.min(1,1-spread.max/.08)),methodSpread:spread,warnings:[]};
}
