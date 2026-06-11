const fmtPct = value => value == null ? "-" : `${(value * 100).toFixed(1)}%`;
const fmtMoney = value => new Intl.NumberFormat("zh-CN", {style:"currency", currency:"CNY", maximumFractionDigits:0}).format(value || 0);
async function load(){
  const [signals,risk]=await Promise.all([fetch('/api/signals/today').then(r=>r.json()),fetch('/api/risk/bankroll/status').then(r=>r.json())]);
  document.querySelector('#empty').style.display=signals.length?'none':'block';
  document.querySelector('#signals').innerHTML=signals.map(s=>`<tr><td class="match"><strong>${s.home_team} vs ${s.away_team}</strong><span>${s.league} · ${new Date(s.kickoff_time).toLocaleString('zh-CN')}</span></td><td><span class="tag ${s.status}">${s.status}</span><div>${s.option||'-'} · ${s.confidence}</div></td><td>${fmtPct(s.probability)}</td><td>${s.sp?.toFixed(2)||'-'}</td><td>${s.fair_odds?.toFixed(2)||'-'}</td><td class="${s.ev>=0?'positive':'negative'}">${fmtPct(s.ev)}</td><td>${fmtMoney(s.stake)}</td><td class="reason">${s.reasons.join('；')}</td></tr>`).join('');
  const bets=signals.filter(s=>s.status==='BET').length, watches=signals.filter(s=>s.status==='WATCH').length;
  document.querySelector('#metrics').innerHTML=[['今日比赛',signals.length],['通过推荐',bets],['观察信号',watches],['默认本金',fmtMoney(risk.bankroll)]].map(x=>`<div class="metric"><small>${x[0]}</small><strong>${x[1]}</strong></div>`).join('');
  document.querySelector('#risk').innerHTML=`<div class="limits"><div class="limit">单场上限<strong>${fmtMoney(risk.single_limit)}</strong></div><div class="limit">单日上限<strong>${fmtMoney(risk.daily_limit)}</strong></div><div class="limit">单周上限<strong>${fmtMoney(risk.weekly_limit)}</strong></div></div><p class="reason">${risk.rules.join(' · ')}</p>`;
}
document.querySelector('#refresh').addEventListener('click',load);load().catch(e=>{document.querySelector('#empty').textContent=`加载失败：${e.message}`});

