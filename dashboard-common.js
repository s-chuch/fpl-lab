// Shared utilities for index.html and bacalhau.html — kept in one place so a
// fix (like escaping) only has to be made once instead of drifting between pages.
const TZ="America/Toronto";
function toToronto(s){
  if(s==null||s==="") return "-";
  const raw=String(s).trim();
  if(/\b(EDT|EST)\b/i.test(raw) && !/UTC/i.test(raw)) return raw.replace(/\bUTC\b/g,"").trim()+" (Toronto)";
  let d=null;
  const m=raw.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::(\d{2}))?\s*(UTC|Z)?$/i);
  if(m) d=new Date(m[1]+"T"+m[2]+":"+(m[3]||"00")+"Z");
  else { const ms=Date.parse(raw); if(!isNaN(ms)) d=new Date(ms); }
  if(!d||isNaN(+d)) return raw;
  return new Intl.DateTimeFormat("en-CA",{timeZone:TZ,weekday:"short",month:"short",day:"numeric",hour:"numeric",minute:"2-digit",hour12:true,timeZoneName:"short"}).format(d);
}
const fmt=n=>n==null?"-":Number(n).toLocaleString();
const sign=n=>n==null?"-":(n>0?"+"+n:String(n));
const cls=n=>n==null?"":n>0?"pos":n<0?"neg":"";
// Escape untrusted text (scraped article titles, X posts, other managers' FPL
// team/league names) before it goes into innerHTML — none of it is ours to trust.
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function safeHref(u){try{const p=new URL(String(u||""),location.href);if(p.protocol==="http:"||p.protocol==="https:")return p.href;}catch(e){}return "#";}
function trNet(t){const n=Number(String(t&&t.net!=null?t.net:0).replace("+",""));return Number.isFinite(n)?n:0;}
// Rival gap-trend/chip/fixture note for the Leagues tab. pronoun="you" (index.html,
// your own decisions) or "they" (bacalhau.html, auditing someone else's squad) —
// same underlying refresh.py data (build_tactics' rival_ctx), just the wording.
function trendNote(gt, pronoun){
  const subj=pronoun==="they"?"they":"you", obj=pronoun==="they"?"them":"you";
  if(gt==null) return null;
  if(gt>0) return subj+" closed "+gt+" last GW";
  if(gt<0) return "gained "+(-gt)+" on "+obj+" last GW";
  return "even with "+obj+" last GW";
}
function rivalExtra(card, pronoun){
  if(!card) return "";
  const bits=[];
  const tn=trendNote(card.gap_trend, pronoun); if(tn) bits.push(tn);
  if(card.chips_used&&card.chips_used.length) bits.push("used "+card.chips_used.join(", "));
  if(card.fixture) bits.push(card.fixture.label.toLowerCase()+" fixtures ("+card.fixture.avg_fdr+")");
  return bits.length?` <span class="note">— ${esc(bits.join(", "))}</span>`:"";
}
const NEWS_ALIAS=[["de cuyper","De Cuyper"],["decuyper","De Cuyper"],["joao pedro","João Pedro"],["joão pedro","João Pedro"],["szoboszlai","Szoboszlai"],["szobos","Szoboszlai"],["b.fernandes","B.Fernandes"],["fernandes","B.Fernandes"],["calvert-lewin","Calvert-Lewin"],["gakpo","Gakpo"],["isak","Isak"],["rogers","Rogers"],["palmer","Palmer"],["haaland","Haaland"],["wissa","Wissa"],["shaw","Shaw"],["gibbs-white","Gibbs-White"],["gibbs white","Gibbs-White"],["gvardiol","Gvardiol"],["saka","Saka"]];
function normTxt(s){return String(s||"").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"");}
function agreedPool(){const N=window.FPL_NEWS||{},X=window.FPL_X||{}; return [].concat((N.agreed||[]).map(x=>({text:x.text,from:"News",player:x.player,club:x.club,tags:x.tags})),(X.agreed||[]).map(x=>({text:x.text,from:"X",player:x.player,club:x.club,tags:x.tags})));}
function namesInText(text){const t=normTxt(text), hits=[]; for(const [key,name] of NEWS_ALIAS){ if(t.includes(normTxt(key)) && !hits.includes(name)) hits.push(name);} return hits;}
// news_scrape.py now discovers trending players dynamically and tags each theme
// with the exact player it found (it.player), rather than the page having to
// re-derive a name from free text via the fixed NEWS_ALIAS list below. Prefer
// that structured field; fall back to NEWS_ALIAS matching for X items (X live
// ingest and manual seeds are curated free text and don't carry a player field).
const CHIP_LABELS={bboost:"Bench Boost","3xc":"Triple Captain",freehit:"Free Hit",wildcard:"Wildcard"};
function fmtCountdown(ms){
  if(ms<=0) return "Locked";
  const s=Math.floor(ms/1000);
  const d=Math.floor(s/86400), h=Math.floor(s%86400/3600), m=Math.floor(s%3600/60), sec=s%60;
  // Always includes seconds, even at day-scale — without them, a tick every
  // 1000ms is invisible for minutes at a time and reads as frozen rather
  // than live (this was reported as "not counting down" for a far-off GW).
  if(d>0) return d+"d "+h+"h "+m+"m "+sec+"s";
  if(h>0) return h+"h "+m+"m "+sec+"s";
  return m+"m "+sec+"s";
}
// The next not-yet-passed deadline, from plan.upcoming (already carries a raw
// UTC timestamp per GW) — the countdown ticks off the real clock, so it stays
// accurate between refreshes even though the rest of the page is a snapshot.
function nextDeadline(D){
  const up=(D.plan&&D.plan.upcoming)||[];
  const next=up.find(u=>u.deadline_utc && !u.deadline_passed);
  if(!next) return null;
  const ts=Date.parse(next.deadline_utc);
  if(isNaN(ts)) return null;
  return {gw:next.gw, ts, label:next.deadline||""};
}
function startDeadlineBanner(D, elId){
  const el=document.getElementById(elId); if(!el) return;
  const nd=nextDeadline(D);
  if(!nd){ el.style.display="none"; return; }
  let timer=null;
  const tick=()=>{
    const ms=nd.ts-Date.now();
    el.innerHTML=`<span>Next deadline · GW${nd.gw}${nd.label?" ("+esc(nd.label)+")":""}</span><b>${esc(fmtCountdown(ms))}</b>`;
    if(ms<=0 && timer) clearInterval(timer);
  };
  tick();
  timer=setInterval(tick,1000);
}
// FPL's own 2026/27 rule change: price changes now land at midnight UK time
// (not the old 1:30am GMT/2:30am BST cutoff). Computed via Intl against
// Europe/London rather than hardcoding a UTC offset, so it stays correct
// across the GMT/BST switch: take "tomorrow" in London as a UTC midnight
// guess, then correct by however many hours London actually is ahead of UTC
// at that instant (0 in GMT, 1 in BST).
function nextLondonMidnight(){
  const now=new Date();
  const ymd=new Intl.DateTimeFormat("en-CA",{timeZone:"Europe/London",year:"numeric",month:"2-digit",day:"2-digit"}).format(now);
  const [y,m,d]=ymd.split("-").map(Number);
  let candidate=Date.UTC(y,m-1,d+1,0,0,0);
  const londonHour=parseInt(new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/London",hour:"2-digit",hour12:false}).format(new Date(candidate)),10);
  candidate-=(londonHour%24)*3600000;
  return candidate;
}
function startPriceCountdown(elId){
  const el=document.getElementById(elId); if(!el) return;
  let nextTs=nextLondonMidnight();
  const tick=()=>{
    let ms=nextTs-Date.now();
    if(ms<=0){ nextTs=nextLondonMidnight(); ms=nextTs-Date.now(); }
    // Instant is fixed by FPL's rule (midnight UK time); label it in the
    // viewer's own timezone rather than UK time, since London/Toronto DST
    // switchover dates don't line up, so a hardcoded clock time would be
    // wrong for a week or two each spring/fall.
    const local=new Intl.DateTimeFormat("en-US",{timeZone:TZ,hour:"numeric",minute:"2-digit",hour12:true,timeZoneName:"short"}).format(new Date(nextTs));
    // "Today"/"Tomorrow" per the viewer's own calendar date, not the UTC one
    // — near midnight Toronto time, the raw UTC date can already have
    // rolled over while it's still "today" locally (or vice versa).
    const dayFmt=d=>new Intl.DateTimeFormat("en-CA",{timeZone:TZ}).format(d);
    const day=dayFmt(new Date(nextTs))===dayFmt(new Date())?"Today":"Tomorrow";
    el.innerHTML=`<span>Next price change (${day} ${esc(local)})</span><b>${esc(fmtCountdown(ms))}</b>`;
  };
  tick();
  setInterval(tick,1000);
}
// Flags a chip active for the live/just-locked GW or already queued for the
// next one, so a chip play surfaces as soon as it's visible instead of only
// on the Chips tab. chips_official only keeps the latest use of each chip
// name, which is exactly the one worth alerting on.
function chipAlertBanner(D){
  const co=D.chips_official||{}, dl=D.deadline||{};
  const targets=new Set([dl.current_gw, dl.next_gw, dl.locked_gw].filter(x=>x!=null));
  const hits=Object.keys(CHIP_LABELS).filter(k=>co[k]!=null && targets.has(co[k])).map(k=>({gw:co[k],label:CHIP_LABELS[k]}));
  if(!hits.length) return "";
  const team=esc((D.team&&D.team.name)||"Team");
  const lines=hits.map(h=>`${team} played <b>${esc(h.label)}</b> in GW${h.gw}.`).join(" ");
  return `<div class="chip-alert">${lines}</div>`;
}
// One account's own post history over time, not cross-account consensus
// like News/X — so unlike those tabs this has no pronoun/team framing and
// renders identically on both dashboards.
function renderGreekGodTab(){
  const G=window.FPL_GREEKGOD||{};
  const TAG_LABEL={called_it:"Called it","captain talk":"Captain","transfer target":"Transfer",chip:"Chip"};
  const VERDICT_CLASS={good:"free",bad:"used",mixed:"mid"};
  const mentions=(G.player_mentions||[]).map(m=>`<div class="chip">${esc(m.name)}${m.club?" · "+esc(m.club):""} · ${m.count}</div>`).join("")||`<p class="note">No player mentions tracked yet.</p>`;
  const clubs=(G.club_mentions||[]).map(c=>`<div class="chip">${esc(c.club)} · ${c.count}</div>`).join("")||`<p class="note">No club mentions tracked yet.</p>`;
  const calls=(G.calls||[]).map(c=>{
    const tags=(c.tags||[]).map(t=>`<span class="pill ${t==="called_it"?"free":"used"}">${esc(TAG_LABEL[t]||t)}</span>`).join(" ");
    const graded=(c.graded||[]).map(g=>{
      if(g.verdict==="pending") return `<span class="note">${esc(g.player)}: GW${g.gw} not played yet</span>`;
      return `<span class="pill ${VERDICT_CLASS[g.verdict]||""}">${esc(g.player)} GW${g.gw} · ${g.pts}pt${g.pts===1?"":"s"} (${esc(g.verdict)})</span>`;
    }).join(" ");
    const link=c.url?`<p class="note"><a href="${safeHref(c.url)}" target="_blank" rel="noopener">View post</a></p>`:"";
    return `<li><span class="who">${esc(toToronto(c.at))}</span> ${tags}<div class="detail">${esc(c.text||"")}</div>${graded?`<div class="detail">${graded}</div>`:""}${link}</li>`;
  }).join("")||`<li><span class="note">No captain/transfer/chip calls or predictions tagged yet.</span></li>`;
  const range=(G.earliest&&G.latest)?`${toToronto(G.earliest)} → ${toToronto(G.latest)}`:"—";
  const cg=G.call_grades||{};
  const record=cg.graded?`<div class="card"><h2>Captain/transfer call record</h2><p class="note">${cg.good_pct}% good · ${cg.mixed_pct}% mixed · ${cg.bad_pct}% bad — ${cg.graded} graded call${cg.graded===1?"":"s"}${cg.pending?`, ${cg.pending} pending (GW not played yet)`:""}.</p><p class="note">Auto-graded from actual points: a captain call is "good" at 8+ points, "bad" at 2 or fewer; a transfer target is "good" at 6+, "bad" at 1 or fewer. Everything in between is "mixed". This is a blunt heuristic on whichever single GW the call was made for, not a judgment of the underlying reasoning.</p></div>`:"";
  document.getElementById("greekgod").innerHTML=`<div class="card"><h2>@${esc(G.handle||"greekgodFpl")}</h2><p class="note">${G.post_count??0} posts archived · ${range}</p><p class="note">Live X ingest only started partway through this season — coverage begins from when tracking started, not GW1. "Called it" flags self-referential prediction language for you to judge against what actually happened — that part still isn't automated.</p></div>${record}<div class="card"><h2>Most-mentioned players</h2><div class="xi">${mentions}</div></div><div class="card"><h2>Most-mentioned clubs</h2><div class="xi">${clubs}</div></div><div class="card"><h2>Captain / transfer / chip calls</h2><ul class="chiplist">${calls}</ul></div>`;
}
function newsVsSquad(squadNames, startedNames, clubsByName){
  const have=new Set((squadNames||[]).map(n=>n)); const start=new Set(startedNames||[]); const owned=[], missing=[], fade=[], caps=[];
  for(const it of agreedPool()){
    const t=normTxt(it.text); const names=it.player?[it.player]:namesInText(it.text);
    const isFade=/fade|sell into|sell /.test(t); const isCap=/captain/.test(t); const isIn=it.player?true:/transfer in|to target|popular forward|priority/.test(t);
    if(isCap) caps.push(it.text);
    if(isFade){ const startedUnited=(startedNames||[]).filter(n=>(clubsByName[n]||"")==="MUN"); const hit=names.filter(n=>start.has(n)).concat(startedUnited); const uniq=[...new Set(hit)]; if(uniq.length) fade.push(uniq.join(", ")+" · "+it.text); continue; }
    const mine=names.filter(n=>have.has(n)); const other=names.filter(n=>!have.has(n));
    if(mine.length) owned.push(mine.join(", ")+" · "+it.text);
    if(other.length && isIn) missing.push(other.join(", ")+" · "+it.text);
  }
  return {owned, missing, fade, caps};
}
