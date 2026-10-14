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
// Player name + club folded into one cell, club stacked on its own line
// below the name ("Groß" / "(BHA)") — used by every compact player table
// so Club doesn't need its own column everywhere.
function nameCell(name,club){return `${esc(name)}${club?`<br><span style="color:var(--muted);font-size:10px">(${esc(club)})</span>`:""}`;}
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
function agreedPool(){const N=window.FPL_NEWS||{}; return (N.agreed||[]).map(x=>({text:x.text,from:"News",player:x.player,club:x.club,tags:x.tags,sources:x.sources}));}
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
// on the Chips tab. chips_official has a key per play (chip, and chip_h2 for the second half).
function chipAlertBanner(D){
  const co=D.chips_official||{}, dl=D.deadline||{};
  const targets=new Set([dl.current_gw, dl.next_gw, dl.locked_gw].filter(x=>x!=null));
  const hits=Object.keys(co).filter(k=>CHIP_LABELS[k.replace(/_h2$/,"")] && co[k]!=null && targets.has(co[k])).map(k=>({gw:co[k],label:CHIP_LABELS[k.replace(/_h2$/,"")]}));
  if(!hits.length) return "";
  const team=esc((D.team&&D.team.name)||"Team");
  const lines=hits.map(h=>`${team} played <b>${esc(h.label)}</b> in GW${h.gw}.`).join(" ");
  return `<div class="chip-alert">${lines}</div>`;
}
// One account's own post history over time, not cross-account consensus
// like News — so unlike those tabs this has no pronoun/team framing and
// renders identically on both dashboards.
// Freshness line + stale-data banner for the News tab (shared by both pages).
function freshnessMeta(obj, kind){
  const gen=obj.generated_at?esc(toToronto(obj.generated_at)):esc(obj.generated_at_et||"—");
  const cut=obj.cutoff?esc(toToronto(obj.cutoff)):"—";
  const bits=[`Scraped ${gen}`, `cutoff ${cut}`];
  if(obj.mode) bits.push("mode "+esc(obj.mode));
  return `<p class="note">${bits.join(" · ")}</p>`;
}
function staleWarn(obj, kind){
  // News is only stale when the scrape itself is old (a run that finds no new articles on fresh data is normal)
  const t=new Date(String(obj.generated_at||"").replace(" UTC","Z").replace(" ","T")).getTime();
  const ageH=isNaN(t)?null:(Date.now()-t)/3600000;
  if(ageH!=null && ageH>24) return `<div class="warn">News was last scraped ${Math.round(ageH)}h ago - themes may be out of date.</div>`;
  if(!(obj.agreed||[]).length && !(obj.split||[]).length) return `<div class="warn">No player themes in the latest scrape.</div>`;
  return "";
}
function newsVsSquad(squadNames, startedNames, clubsByName){
  const have=new Set((squadNames||[]).map(n=>n)); const start=new Set(startedNames||[]); const owned=[], missing=[], fade=[], caps=[];
  for(const it of agreedPool()){
    const t=normTxt(it.text); const names=it.player?[it.player]:namesInText(it.text);
    const isFade=/fade|sell into|sell /.test(t); const isCap=/captain/.test(t); const isIn=it.player?true:/transfer in|to target|popular forward|priority/.test(t);
    if(isCap) caps.push(it.text);
    if(isFade){ const aboutUnited=it.club==="MUN"||/\bman(?:chester)? (?:utd|united)\b|\bmun\b/.test(t); const startedUnited=aboutUnited?(startedNames||[]).filter(n=>(clubsByName[n]||"")==="MUN"):[]; const hit=names.filter(n=>start.has(n)).concat(startedUnited); const uniq=[...new Set(hit)]; if(uniq.length) fade.push(uniq.join(", ")+" · "+it.text); continue; }
    // Structured fields (it.sources/it.tags) let the Plan-tab card render a
    // real table instead of one paragraph per player — club is only trusted
    // when the item names exactly one player (it.club can't be right for a
    // name pulled from NEWS_ALIAS fallback matching against a multi-name item).
    const mine=names.filter(n=>have.has(n)); const other=names.filter(n=>!have.has(n));
    const club=names.length===1?it.club:null, mentions=(it.sources||[]).length, tags=it.tags||[];
    mine.forEach(n=>owned.push({name:n, club, mentions, tags}));
    if(isIn) other.forEach(n=>missing.push({name:n, club, mentions, tags}));
  }
  return {owned, missing, fade, caps};
}

// Wildcard tab: how the hand-captured wildcard squad (W.xi + W.bench) lines up
// against the other managers' CURRENT squads in the European Super League
// mini-league (id 125784) — what the room owns, what you'd be fading, who you'd
// overlap with. Built from D.leagues.mini[].member_squads (already in the data
// file), excluding the page owner's own row so the room is "the other N".
const ESL_ID=125784;
function eslWildcardCard(W,D,who){
  const lg=((D&&D.leagues&&D.leagues.mini)||[]).find(l=>l.id===ESL_ID);
  const rivals=((lg&&lg.member_squads)||[]).filter(m=>!m.me);
  const mine=((W&&W.xi)||[]).concat((W&&W.bench)||[]);
  if(!rivals.length||!mine.length) return "";
  const n=rivals.length, key=p=>p.name+"|"+p.club;
  const own={}, cap={}, info={};
  rivals.forEach(m=>{
    (m.xi||[]).concat(m.bench||[]).forEach(p=>{own[key(p)]=(own[key(p)]||0)+1;info[key(p)]=p;});
    const c=(m.xi||[]).find(p=>p.name===m.captain);
    if(c) cap[key(c)]=(cap[key(c)]||0)+1;
  });
  const pct=c=>Math.round(100*c/n);
  const diffMax=Math.max(1,Math.floor(n/4));
  const tag=c=>c>=Math.ceil(n/2)?["Template","pos"]:c===0?["Unique","used"]:c<=diffMax?["Differential","mid"]:["Shared",""];
  const myKeys=new Set(mine.map(key));
  const rows=mine.map(p=>({p,c:own[key(p)]||0,cc:cap[key(p)]||0}))
    .sort((a,b)=>b.c-a.c)
    .map(({p,c,cc})=>{const [t,k]=tag(c);
      return `<tr><td>${nameCell(p.name,p.club)}${p.captain?` <span class="pill used">C</span>`:p.vice?` <span class="pill free">VC</span>`:""}</td><td>${c}/${n} (${pct(c)}%)</td><td>${cc||"–"}</td><td><span class="pill ${k}">${t}</span></td></tr>`;}).join("");
  const nTemplate=mine.filter(p=>(own[key(p)]||0)>=Math.ceil(n/2)).length;
  const nDiff=mine.filter(p=>(own[key(p)]||0)<=diffMax).length;
  const missing=Object.keys(own).filter(k=>!myKeys.has(k)&&own[k]>=Math.max(3,Math.ceil(n/3)))
    .sort((a,b)=>own[b]-own[a]).slice(0,8)
    .map(k=>`<li><span class="who">${esc(info[k].name)} (${esc(info[k].club)}) · ${esc(info[k].pos)}</span><div class="detail">${own[k]}/${n} rivals (${pct(own[k])}%) own him${cap[k]?` · captained by ${cap[k]}`:""}</div></li>`).join("");
  const overlaps=rivals.map(m=>{
    const set=new Set((m.xi||[]).concat(m.bench||[]).map(key));
    return {m,shared:mine.filter(p=>set.has(key(p))).length};
  }).sort((a,b)=>(a.m.rank||99)-(b.m.rank||99));
  const avgOverlap=(overlaps.reduce((s,o)=>s+o.shared,0)/overlaps.length).toFixed(1);
  const ovRows=overlaps.map(o=>`<tr><td>${esc(o.m.team)}<br><span style="color:var(--muted);font-size:10px">#${o.m.rank} · ${fmt(o.m.pts)} pts</span></td><td>${o.shared}/${mine.length}</td><td>${esc(o.m.captain||"–")}</td></tr>`).join("");
  const wc=mine.find(p=>p.captain), wcKey=wc&&key(wc);
  const capTally={};rivals.forEach(m=>{if(m.captain)capTally[m.captain]=(capTally[m.captain]||0)+1;});
  const top=Object.entries(capTally).sort((a,b)=>b[1]-a[1])[0];
  const capLine=wc?`<li>Wildcard captain <b>${esc(wc.name)}</b>: ${cap[wcKey]||0} of ${n} rivals captain him${top?` · the room's most-captained is <b>${esc(top[0])}</b> (${top[1]})`:""}</li>`:"";
  return `<div class="card"><h2>${esc(who||"Wildcard")} vs ${esc((lg&&lg.name)||"the European Super League")}</h2><ul class="note-list"><li>Compares the wildcard squad above with the other ${n} managers' <b>current</b> squads (their wildcards, if any, aren't visible until they confirm)</li><li><b>${nTemplate}</b> of ${mine.length} picks are template (owned by half the room or more) · <b>${nDiff}</b> are differentials (owned by ${diffMax} or fewer) · average overlap with a rival: <b>${avgOverlap}</b> of ${mine.length}</li>${capLine}</ul><table class="table-compact"><thead><tr><th style="width:36%">Player</th><th style="width:26%">Room owns</th><th style="width:14%">Cap</th><th style="width:24%">Type</th></tr></thead><tbody>${rows}</tbody></table>${missing?`<h3>Room template you're not playing</h3><ul class="chiplist">${missing}</ul>`:""}<h3>Overlap with each rival</h3><table class="table-compact"><thead><tr><th style="width:50%">Manager</th><th style="width:20%">Shared</th><th style="width:30%">Captain</th></tr></thead><tbody>${ovRows}</tbody></table></div>`;
}

// Remember the open tab across a browser refresh. The URL fragment (#tab=<id>)
// wins, so a refreshed or bookmarked URL reopens the same tab; localStorage is
// the fallback for a fresh visit to the bare URL. "#tab=" rather than "#<id>"
// because the sections carry those ids and a bare fragment would scroll to one.
function restoreTab(groups,key,defGroup,defTab){
  const find=id=>groups.find(g=>g.tabs.some(t=>t[0]===id));
  let id=null;
  const m=(location.hash||"").match(/^#tab=([\w-]+)$/);
  if(m&&find(m[1])) id=m[1];
  if(!id){try{const s=localStorage.getItem(key);if(s&&find(s)) id=s;}catch(e){}}
  if(!id) return {group:defGroup,tab:defTab};
  return {group:find(id).id,tab:id};
}
function saveTab(key,id){
  try{history.replaceState(null,"",location.pathname+location.search+"#tab="+id);}catch(e){}
  try{localStorage.setItem(key,id);}catch(e){}
}

// "Rivals that matter" card for a mini-league: the managers closest to you on
// points (league_tactics.pick_contenders), labelled by their real table
// position, with the chips each can still play this half — the thing that lets
// a close rival swing a week. Replaces the old fixed top-2 / bottom-2 strip.
const CHIP_SHORT={wildcard:"Wildcard",freehit:"Free Hit",bboost:"Bench Boost","3xc":"Triple Captain"};
function rivalsCard(tac,leagueName,pronoun){
  if(!tac) return "";
  const list=tac.contenders;
  if(!Array.isArray(list)||!list.length) return `<div class="card"><h2>Rivals that matter · ${esc(leagueName||"league")}</h2><p class="note">Computed on the next refresh.</p></div>`;
  const chipNames=a=>a.map(c=>CHIP_SHORT[c]||c).join(", ");
  const rows=list.map(c=>{
    const gap=c.gap==null?"?":(c.gap>0?`${c.gap} ahead`:c.gap<0?`${-c.gap} behind`:"level");
    const left=c.chips_left==null?`<span class="note">chips: unknown</span>`:(c.chips_left.length?`chips left: <b>${esc(chipNames(c.chips_left))}</b>`:`<span class="note">no chips left this half</span>`);
    const used=(c.chips_used&&c.chips_used.length)?` · used: ${esc(chipNames(c.chips_used))}`:"";
    const tn=trendNote(c.gap_trend,pronoun||"you");
    const extra=[tn,c.fixture?c.fixture.label.toLowerCase()+" fixtures ("+c.fixture.avg_fdr+")":null].filter(Boolean);
    return `<li><span class="who">P${c.rank} · ${esc(c.name||"?")} · ${c.pts??"?"} (${gap})</span><div class="detail">${left}${used}${extra.length?` · ${esc(extra.join(", "))}`:""}</div></li>`;
  }).join("");
  return `<div class="card"><h2>Rivals that matter · ${esc(leagueName||"league")}</h2><ul class="note-list"><li>The managers closest to you on points (within 25, at least 3) — not simply 2nd, 3rd and last</li><li>"Chips left" = unused in the current half-season window; each chip comes back once per half</li></ul><ul class="chiplist">${rows}</ul>${tac.you_rank===1?`<p class="note">They can still chip a week you cannot match. A −4 this half is a gift unless the incoming player is out for weeks.</p>`:""}</div>`;
}


// Fixture ticker: every club's opponent for the next few unlocked gameweeks, coloured by
// FDR, your clubs on top (with the players you own there), then the rest kindest-run
// first. Home = CAPITALS, away = lower case. A blank gameweek shows a dash; a double
// stacks two fixtures. Built from strategy.fixtures.ticker (refresh.py build_strategy).
function fixtureTickerCard(F,who){
  const T=F&&F.ticker; if(!T||!(T.rows||[]).length) return "";
  const cell=c=>{
    if(!c.fx.length) return `<td class="f blank">–</td>`;
    const txt=c.fx.map(f=>esc(f.side==="H"?String(f.opp).toUpperCase():String(f.opp).toLowerCase())).join("<br>");
    return `<td class="f d${Math.min(5,Math.max(1,Math.round(c.fx.reduce((a,f)=>a+(f.fdr||3),0)/c.fx.length)))}" title="${esc(c.fx.map(f=>f.opp+" ("+f.side+") FDR "+(f.fdr??"?")).join(" + "))}">${txt}</td>`;
  };
  const head=`<thead><tr><th style="width:20%">Club</th>${T.gws.map(g=>`<th style="width:${Math.floor(80/T.gws.length)}%">GW${g}</th>`).join("")}</tr></thead>`;
  const row=r=>`<tr class="${r.squad.length?"mine":""}"><td><b>${esc(r.club)}</b>${r.squad.length?`<span class="who">${esc(r.squad.join(", "))}</span>`:""}</td>${T.gws.map(g=>cell(r.cells.find(c=>c.gw===g)||{fx:[]})).join("")}</tr>`;
  const mine=T.rows.filter(r=>r.squad.length), rest=T.rows.filter(r=>!r.squad.length);
  return `<div class="card"><h2>Fixture ticker · next ${T.gws.length} GWs</h2><ul class="note-list"><li>Every club's opponents for the gameweeks you can still change, coloured by difficulty</li><li>Gold-edged rows are ${who==="you"?"your":esc(who)+"'s"} clubs, with the players ${who==="you"?"you":"they"} own there; the rest are ordered kindest run first — the place to look for targets</li></ul><table class="table-compact ticker">${head}<tbody>${mine.map(row).join("")}${rest.length?`<tr><td colspan="${T.gws.length+1}" style="color:var(--muted);font-size:10px;letter-spacing:.1em;text-transform:uppercase;padding-top:10px">Other clubs · easiest run first</td></tr>`:""}${rest.map(row).join("")}</tbody></table><ul class="legend-list"><li>CAPITALS = home, lower case = away · a dash is a blank gameweek, two names stacked is a double</li><li>Colour: green = easy (FDR 1–2), grey = 3, amber = 4, red = hard (5)</li></ul></div>`;
}

// Captain tab (Review): same You / Process / Hindsight shape as the bench audit. See
// refresh.py build_captain_board. Newest GW open, older ones folded.
function captainBlock(key,title,open,D){
  const b=D.captain_board&&D.captain_board[key]; if(!b) return "";
  const max=Math.max(b.you,b.process,b.hindsight,1);
  const pct=v=>Math.max(4,Math.round(100*v/max));
  const row=(l,v,k)=>`<div class="barrow"><span>${l}</span><div class="track"><i class="${k||""}" style="width:${pct(v)}%"></i></div><b>${v}</b></div>`;
  const good=b.you>=b.process;
  const chipTag=b.chip==="3xc"?" · Triple Captain":"";
  const eff=b.effective&&b.effective!==b.captain[0]?`<li>${esc(b.captain[0])} did not play, so the vice ${esc(b.effective)} took the armband</li>`:"";
  const opts=(b.options||[]).map(([n,p])=>{
    const tags=[n===b.captain[0]?"C":"",b.vice&&n===b.vice[0]?"VC":"",n===b.process_pick[0]?"P":""].filter(Boolean).join("/");
    const k=n===b.captain[0]?(good?"chip ok":"chip process"):"chip sit";
    return `<div class="${k}">${esc(n)} · ${p}${tags?` (${tags})`:""}</div>`;
  }).join("");
  const why=[`Your captain: <b>${esc(b.captain[0])}</b> (${b.captain[1]} pts × ${b.mult} = ${b.you})${chipTag}`,
    `Process pick: <b>${esc(b.process_pick[0])}</b> — best points per appearance over the previous GWs${b.process_pick[2]>=0?` (${b.process_pick[2]})`:""}`,
    `Hindsight: <b>${esc(b.best[0])}</b> (${b.best[1]} pts) was the top scorer in your XI`].map(x=>`<li>${x}</li>`).join("")+eff;
  return `<details class="card fold"${open?" open":""}><summary><h2>${title}</h2><span class="foldsum"><b class="${good?"pos":"neg"}">You ${b.you}</b> · Process ${b.process} · Hindsight ${b.hindsight}</span></summary>${row("You",b.you,good?"good":"bad")}${row("Process",b.process)}${row("Hindsight",b.hindsight)}<ul class="why">${why}</ul><p class="note">Top scorers in your XI (C = captain, VC = vice, P = process pick)</p><div class="xi">${opts}</div></details>`;
}
// Prediction scorecard (refresh.py update_pred_log): what the program said its captain would be each gameweek,
// and what that player actually scored once FPL had checked the data.
function predLogCard(D){
  const L=D.pred_log||{};
  const rows=Object.values(L).sort((a,b)=>b.gw-a.gw);
  if(!rows.length) return "";
  const body=rows.map(e=>{
    const done=e.graded;
    const cell=(name,pts)=>name?`${esc(name)}${done&&pts!=null?` <b>${pts}</b>`:""}`:"–";
    return `<tr><td>GW${e.gw}${done?"":` <span class="pill free">open</span>`}</td><td>${cell(e.plan_captain,e.plan_captain_points)}</td><td>${cell(e.ai_captain,e.ai_captain_points)}</td><td>${done?e.best_player_points:"–"}</td></tr>`;
  }).join("");
  const gn=rows.filter(e=>e.graded&&e.news_points&&e.news_points.avg!=null);
  const newsLine=gn.length?`<li>News-agreed players (3+ sites) averaged <b>${(gn.reduce((s,e)=>s+e.news_points.avg,0)/gn.length).toFixed(1)}</b> points when they played, against <b>${(gn.reduce((s,e)=>s+e.news_points.field_avg,0)/gn.length).toFixed(1)}</b> for every player who played (${gn.length} gameweek${gn.length===1?"":"s"})</li>`:`<li>News themes are logged each gameweek and scored here once it is settled</li>`;
  const g=rows.filter(e=>e.graded&&e.plan_captain_points!=null);
  const avg=g.length?(g.reduce((s,e)=>s+e.plan_captain_points,0)/g.length).toFixed(1):null;
  const bestAvg=g.length?(g.reduce((s,e)=>s+e.best_player_points,0)/g.length).toFixed(1):null;
  return `<div class="card"><h2>Captain scorecard</h2><ul class="note-list"><li>The captain the program picked before each deadline, and the raw points that player scored (before the armband multiple)</li>${newsLine}<li>Best player = the top scorer in the whole league that week, for scale${avg?` · graded gameweeks: Plan captain averaged <b>${avg}</b> vs <b>${bestAvg}</b> for the best player`:" · no gameweek graded yet"}</li></ul><table class="table-compact"><thead><tr><th>GW</th><th>Plan captain</th><th>AI captain</th><th>Best player</th></tr></thead><tbody>${body}</tbody></table></div>`;
}
// "This GW" card: the answer to "what do I do before the deadline" in one place, built from what the Plan,
// Chips and AI team already know (one captain, like-for-like transfer advice, fitness flags, chips).
function thisGwCard(D){
  try{
    const P=D.plan||{}, up=(P.upcoming||[]).filter(u=>!u.deadline_passed);
    const u=up[0]; if(!u) return "";
    const key="gw"+u.gw, xi=(((P.xis||{})[key]||{}).xi)||[];
    const bare=n=>String(n).split(" (")[0];
    const cap=xi.find(n=>/ \(C\)$/.test(n)), vice=xi.find(n=>/ \(VC\)$/.test(n));
    const I=(window.planIntel&&window.planIntel(D))||{};
    const transfer=(I.action&&!I.cleared)?`${esc(I.moveLine||"")} <span class="note">(${esc(I.ft!=null?I.ft+" FT":"")}${D.team&&D.team.bank!=null?" · bank £"+Number(D.team.bank).toFixed(1):""})</span>`:esc(((P.transfer||{}).action==="TRANSFER"&&(P.transfer||{}).move)?`${P.transfer.move.out} → ${P.transfer.move.inn}`:"Roll the free transfer");
    const av=P.availability||{};
    const flags=xi.map(bare).filter(n=>av[n]&&(av[n].kind==="out"||av[n].kind==="doubt")).map(n=>`<span class="pill used">${esc(n)} ${esc(av[n].label||av[n].kind)}</span>`).join(" ");
    const chipRecs=(I.chipRows||[]).filter(c=>c.rec==="CONSIDER").map(c=>esc(c.label)+" (GW"+c.gw+")");
    const ai=D.ai_team&&D.ai_team.plan;
    const aiLine=ai?`AI team ${ai.locked?"locked its GW"+ai.gw+" plan":"locks its GW"+ai.gw+" plan "+esc(aiWhen(ai.lock_at))}`:"";
    const when=u.deadline||(u.deadline_utc?toToronto(u.deadline_utc):"");
    return `<div class="card"><h2>This gameweek · GW${u.gw}</h2><p class="note">Deadline ${esc(when)}</p><ul class="chiplist"><li><span class="who">Captain</span><span><b>${esc(cap?bare(cap):"–")}</b>${vice?` · vice ${esc(bare(vice))}`:""}</span></li><li><span class="who">Transfer</span><span>${transfer}</span></li><li><span class="who">XI fitness</span><span>${flags||"No injury or doubt flags in the XI"}</span></li><li><span class="who">Chips</span><span>${chipRecs.length?chipRecs.join(", "):"No chip play recommended"}</span></li>${aiLine?`<li><span class="who">AI team</span><span>${aiLine}</span></li>`:""}</ul></div>`;
  }catch(e){ return ""; }
}
// Elite ownership (signals.build_elite_ownership): what the best managers hold and captain. FPL only serves the
// first 50 of the overall table, so this is a top-50 sample.
function eliteCard(D){
  const E=D.elite||{}; if(!E.n) return "";
  const mine=new Set(((D.plan||{}).rows||[]).map(r=>r[1]));
  const ownRows=Object.keys(E.own||{}).sort((a,b)=>E.own[b]-E.own[a]).slice(0,12).map(id=>{
    const [name,club,pos]=(E.names||{})[id]||["?","",""];
    const pct=Math.round(100*E.own[id]/E.n);
    return `<tr><td>${esc(name)} <span class="note">${esc(club)}</span></td><td>${esc(pos)}</td><td><b>${pct}%</b></td><td>${mine.has(name)?'<span class="pill used">You own</span>':'<span class="note">–</span>'}</td></tr>`;
  }).join("");
  const caps=Object.keys(E.cap||{}).sort((a,b)=>E.cap[b]-E.cap[a]).slice(0,5).map(id=>`${esc(((E.names||{})[id]||["?"])[0])} <b>${Math.round(100*E.cap[id]/E.n)}%</b>`).join(" · ");
  return `<div class="card"><h2>Elite ownership · ${esc(E.label||"")}</h2><ul class="note-list"><li>GW${E.gw} squads of the best managers in the overall table (FPL only publishes the first 50, so this is a small, elite sample)</li><li>Captains: ${caps||"–"}</li></ul><table class="table-compact"><thead><tr><th>Player</th><th>Pos</th><th>Top 50</th><th>You</th></tr></thead><tbody>${ownRows}</tbody></table></div>`;
}
// Multi-gameweek transfer plan (planner.py): the transfer path with the most expected points over the next few
// gameweeks, hits included, against simply rolling every week.
function plannerCard(D){
  const P=D.planner||{}; if(!(P.steps||[]).length) return "";
  const rows=P.steps.map(s=>{
    const mv=(s.moves||[]).map(m=>`${esc(m.out)} → <b>${esc(m.in)}</b> <span class="note">${esc(m.pos)} · £${m.sell.toFixed(1)}→£${m.cost.toFixed(1)}</span>`).join("<br>")||`<span class="note">Roll${s.ft_after!=null?" · "+s.ft_after+" FT banked":""}</span>`;
    return `<tr><td>GW${s.gw}</td><td style="white-space:normal">${mv}${s.hits?` <b class="neg">-${s.hits*4}</b>`:""}</td><td>${s.xp}</td><td>${esc(s.captain)}</td></tr>`;
  }).join("");
  const head=P.recommend==="follow"
    ?`Following this plan is worth about <b class="pos">+${P.gain}</b> expected points over rolling (${P.plan_xp} vs ${P.roll_xp})`
    :`Rolling every week is as good as any plan (best found: ${sign(P.gain)} over rolling) - nothing is worth a move yet`;
  const first=(P.steps[0].moves||[]).length?`This week: ${P.steps[0].moves.map(m=>esc(m.out)+" → "+esc(m.in)).join(", ")}.`:"This week: roll.";
  return `<div class="card"><h2>Transfer planner · GW${P.gws[0]}-${P.gws[P.gws.length-1]}</h2><ul class="note-list"><li>${head}</li><li>${first} ${P.ft} FT, bank £${Number(P.bank).toFixed(1)} now</li><li>${esc(P.note||"")}</li></ul><table class="table-compact"><thead><tr><th style="width:12%">GW</th><th style="width:46%">Move</th><th style="width:16%">xP</th><th style="width:26%">Captain</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
// Matchday snapshot (live_update.py -> live-data.js, written every ~10 min while matches are in play). The browser
// cannot call FPL's API itself (no CORS), so the page reads that snapshot and refreshes it while it is open.
function liveBar(L,team){
  try{
    const T=L&&L.teams&&L.teams[team]; if(!T) return "";
    const ageMin=(Date.now()-new Date(String(L.generated_at).replace(" UTC","Z").replace(" ","T")).getTime())/60000;
    if(!(ageMin<360)) return "";           // a stale snapshot (match day long over) is not shown as live
    const xi=T.xi.map(p=>`<tr><td>${esc(p.name)}${p.mult>1?" (C)":""}</td><td>${esc(p.pos)}</td><td class="${p.played?"":"note"}">${p.played?p.pts*p.mult+(p.bonus?` <span class="note">+${p.bonus}b</span>`:""):"yet to play"}</td></tr>`).join("");
    const games=(L.games||[]).filter(g=>g.started).map(g=>`${esc(g.home)} ${g.hs??"-"}-${g.as??"-"} ${esc(g.away)}${g.finished?"":" ("+(g.minutes||"")+"')"}`).join(" · ");
    return `<details class="card fold" open><summary><h2>Live · GW${L.gw}</h2><span class="foldsum"><b>${T.points}</b> pts · ${T.yet_to_play} yet to play · updated ${esc(toToronto(L.generated_at))}</span></summary><ul class="note-list"><li>${L.in_play} match${L.in_play===1?"":"es"} in play${games?" — "+games:""}</li><li>Provisional: FPL's live points with bonus so far. Auto-subs and a vice-captain taking over are only applied once the gameweek is settled${T.hits?`; includes -${T.hits} for hits`:""}${T.chip?` · ${esc(T.chip)} active`:""}</li></ul><table class="table-compact"><thead><tr><th style="width:50%">Player</th><th style="width:18%">Pos</th><th>Pts</th></tr></thead><tbody>${xi}</tbody></table><p class="note">Bench: ${T.bench.map(b=>esc(b.name)+" "+(b.played?b.pts:"–")).join(" · ")}</p></details>`;
  }catch(e){ return ""; }
}
function loadLive(team){
  const load=()=>{const s=document.createElement("script"); s.src="live-data.js?t="+Date.now(); s.onload=()=>{const el=document.getElementById("liveBar"); if(el) el.innerHTML=liveBar(window.FPL_LIVE,team); s.remove();}; s.onerror=()=>s.remove(); document.head.appendChild(s);};
  load(); setInterval(load,5*60*1000);
}
function renderCaptain(D){
  const keys=Object.keys(D.captain_board||{}).sort((a,b)=>Number(a.replace(/\D/g,""))-Number(b.replace(/\D/g,""))).reverse();
  const legend=`<ul class="note-list"><li>You = the armband's actual return (captain points × multiplier; the vice if the captain didn't play)</li><li>Process = the starter with the best points per appearance over the previous 3 GWs — knowable at the deadline</li><li>Hindsight = the top scorer in your XI, which nobody can know in advance</li><li>Green You = matched or beat the process pick; red = fell short of it</li></ul>`;
  document.getElementById("captain").innerHTML=predLogCard(D)+eliteCard(D)+(keys.length?keys.map((k,i)=>captainBlock(k,k.toUpperCase(),i===0,D)).join(""):`<div class="card"><h2>Captain audit</h2><p class="note">No finished GW captain audit yet.</p></div>`)+legend;
}

// AI team (ai_team.py): a squad the program picks and plays itself, from GW7, with your money and
// your chips. Plan tab = what it will do (locked 12h before the deadline); Results tab = points made.
function aiWhen(iso){
  try{return new Date(iso).toLocaleString("en-CA",{timeZone:"America/Toronto",weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit",hour12:false})+" ET";}catch(e){return iso||"";}
}
function aiCountdown(iso){
  const ms=new Date(iso).getTime()-Date.now();
  if(!(ms>0)) return "now";
  const h=Math.floor(ms/3600000), m=Math.floor(ms%3600000/60000);
  return h>=24?`${Math.floor(h/24)}d ${h%24}h`:`${h}h ${m}m`;
}
const AI_POS_ORDER=["GKP","DEF","MID","FWD"];
function aiPlanCard(D,who){
  const A=D.ai_team, P=A&&A.plan;
  if(!P) return `<div class="card"><h2>AI team</h2><p class="note">Starts with GW7. Its first plan appears on the next refresh.</p></div>`;
  const sq=Object.fromEntries(P.squad.map(p=>[p.id,p]));
  const tag=id=>id===P.captain?` <span class="pill free">C</span>`:id===P.vice?` <span class="pill used">VC</span>`:"";
  const pill=P.locked?`<span class="pill used">Locked ${esc(aiWhen(P.locked_at))}</span>`:`<span class="pill free">Planned · locks in ${esc(aiCountdown(P.lock_at))}</span>`;
  const xiRows=AI_POS_ORDER.map(pos=>P.xi.filter(i=>sq[i].pos===pos).map(i=>{const p=sq[i];return `<tr><td>${nameCell(p.name,p.club)}${tag(i)}</td><td>${esc(p.pos)}</td><td>£${p.cost.toFixed(1)}</td><td>${esc(p.fixture)}</td><td><b>${p.xp.toFixed(1)}</b></td></tr>`;}).join("")).join("");
  const benchRows=P.bench.map((i,n)=>{const p=sq[i];return `<tr><td>${n+1}. ${nameCell(p.name,p.club)}</td><td>${esc(p.pos)}</td><td>£${p.cost.toFixed(1)}</td><td>${esc(p.fixture)}</td><td>${p.xp.toFixed(1)}</td></tr>`;}).join("");
  const head=`<thead><tr><th style="width:36%">Player</th><th style="width:9%">Pos</th><th style="width:13%">Cost</th><th style="width:30%">Next</th><th style="width:12%">xP</th></tr></thead>`;
  const moves=P.initial
    ?`<li>Starting squad built from scratch (free), £${P.squad_cost.toFixed(1)}m spent, £${P.bank.toFixed(1)}m in the bank</li>`
    :(P.transfers.length?P.transfers.map(t=>`<li>${esc(t.out)} → <b>${esc(t.in)}</b> <span class="note">(+${t.gain} pts${t.hit?", −4 hit":""})</span><div class="detail">Sells for £${(t.sell??0).toFixed(1)}m (bought at £${(t.bought_at??0).toFixed(1)}m) · buys at today's £${(t.cost_in??0).toFixed(1)}m</div></li>`).join(""):`<li>No transfers — rolls ${P.ft_before??0} free transfer${P.ft_before===1?"":"s"}</li>`);
  const chips=(A.chips_available||[]).length?`${(A.chips_available).map(c=>({wildcard:"Wildcard",freehit:"Free Hit",bboost:"Bench Boost","3xc":"Triple Captain"}[c]||c)).join(", ")} available (same as ${who||"you"}) — held, not played yet`:`No chips left (same as ${who||"you"})`;
  const why=P.squad.map(p=>`<li><span class="who">${esc(p.name)}</span><div class="detail">${esc(p.why||"")}</div></li>`).join("");
  return `<div class="card"><h2>AI team · GW${P.gw} plan ${pill}</h2><ul class="note-list"><li>Deadline ${esc(aiWhen(P.deadline))} · it makes its moves ${esc(aiWhen(P.lock_at))} (12h before) and shows them here before then</li><li>Formation <b>${esc(P.formation)}</b> · expected ${P.xp_xi} pts (captain doubled)</li><li>Started as a copy of ${who==="you"?"your":esc(who||"your")+"'s"} GW${A.cloned_from_gw??"?"} team — same 15 players at the prices paid, same bank and free transfers, same chips, same points — and plays independently from GW${A.start_gw??"?"} on: what you do after that does not affect it</li><li>Funds: squad sell value £${(P.sell_value??0).toFixed(1)}m + bank £${(P.bank??0).toFixed(1)}m = <b>£${((P.sell_value??0)+(P.bank??0)).toFixed(1)}m</b> after these moves</li><li>Chips: ${esc(chips)}</li></ul><h3>Transfers (${P.ft_before??0} free available · bank £${(P.bank??0).toFixed(1)}m after)</h3><ul class="note-list">${moves}</ul></div><div class="card"><h2>Starting XI · captain C, vice VC</h2><table class="table-compact">${head}<tbody>${xiRows}</tbody></table><h3>Bench (in auto-sub order)</h3><table class="table-compact">${head}<tbody>${benchRows}</tbody></table><ul class="legend-list"><li>xP = expected points for GW${P.gw}: FPL's form/expected points, our xG/xA model, minutes security, the fixture and availability, plus Understat chance volume</li><li>Money follows FPL's rules: players are sold at their purchase price plus half of any profit (rounded down to 0.1m) and bought at today's price; prices are re-read every refresh and the buys lock in at the lock-time price</li><li>Squad score also weights the next gameweek's fixture so it avoids short-lived picks; transfers must beat a threshold (free moves +0.6, a −4 hit needs +5.5)</li></ul><details class="fold"><summary><h3>Why each pick</h3></summary><ul class="chiplist">${why}</ul></details></div>`;
}
function aiResultsCard(D,who){
  const A=D.ai_team; if(!A) return `<div class="card"><h2>AI team results</h2><p class="note">Nothing yet.</p></div>`;
  const H=Object.values(A.history||{}).sort((a,b)=>b.gw-a.gw);
  if(!H.length) return `<div class="card"><h2>AI team results</h2><p class="note">It starts with the ${A.baseline_points??0} points you had at GW${A.cloned_from_gw??"?"}. GW${A.plan?A.plan.gw:7} is the first gameweek it plays on its own; points appear once that deadline passes.</p></div>`;
  const tot=A.total_points||0, you=A.user_total||0;
  const rows=H.map(p=>{const r=p.result||{};return `<tr><td>GW${p.gw}${r.final?"":` <span class="pill free">live</span>`}</td><td><b>${r.points??"–"}</b></td><td>${p.user_points??"–"}</td><td class="${cls((r.points??0)-(p.user_points??0))}">${p.user_points==null||r.points==null?"–":sign(r.points-p.user_points)}</td><td>${esc(r.captain||"–")}</td></tr>`;}).join("");
  const blocks=H.map((p,i)=>{const r=p.result||{};const L=(r.lines||[]).map(l=>`<tr><td>${esc(l.name)}${l.mult>1?` <span class="pill free">C×${l.mult}</span>`:""}</td><td>${esc(l.pos)}</td><td>${l.played?"":`<span class="note">DNP</span> `}<b>${l.pts*l.mult}</b></td></tr>`).join("");const subs=(r.autosubs||[]).length?`<p class="note">Auto-subs: ${(r.autosubs).map(s=>esc(s.out)+" → "+esc(s.in)).join(", ")}</p>`:"";
    return `<details class="card fold"${i===0?" open":""}><summary><h2>GW${p.gw}</h2><span class="foldsum"><b>${r.points??"–"}</b> pts${r.hits?` (−${r.hits} hit)`:""} · ${esc(who||"you")} ${p.user_points??"–"}</span></summary><table class="table-compact"><thead><tr><th style="width:55%">Player</th><th style="width:20%">Pos</th><th style="width:25%">Pts</th></tr></thead><tbody>${L}</tbody></table>${subs}<p class="note">Bench left unused: ${r.bench_pts??0} pts${r.final?"":" · gameweek still in progress"}</p></details>`;}).join("");
  return `<div class="card"><h2>AI team results</h2><ul class="chiplist"><li><span class="who">Season points</span><span>AI <b>${A.season_points??tot}</b> · ${esc(who||"You")} <b>${A.user_season??you}</b></span><div class="detail">The AI started with the ${A.baseline_points??0} points you had at GW${A.cloned_from_gw??"?"} · gap <b class="${cls((A.season_points??tot)-(A.user_season??you))}">${sign((A.season_points??tot)-(A.user_season??you))}</b></div></li><li><span class="who">Since it went independent</span><span>AI <b>${tot}</b> · ${esc(who||"You")} <b>${you}</b></span><div class="detail">GW${A.start_gw??"?"} onwards · <b class="${cls(tot-you)}">${sign(tot-you)}</b></div></li></ul><table class="table-compact"><thead><tr><th style="width:22%">GW</th><th style="width:18%">AI</th><th style="width:18%">${esc(who||"You")}</th><th style="width:16%">Diff</th><th style="width:26%">Captain</th></tr></thead><tbody>${rows}</tbody></table><ul class="legend-list"><li>AI points use FPL's live scoring: captain doubled (vice if the captain doesn't play), auto-subs in bench order, −4 per extra transfer</li></ul></div>${blocks}`;
}
function renderAiTeam(D,who){
  const a=document.getElementById("aiPlan"), r=document.getElementById("aiResults");
  if(a) a.innerHTML=aiPlanCard(D,who)+aiChangesCard(D.ai_team);
  if(r) r.innerHTML=aiResultsCard(D,who);
}

// Daily check (refresh.py build_daily_check): injuries, news, price moves and new rotation risks for
// everyone you own plus the AI team, compared with the previous run. Shown on the Season tab.
function dailyCheckCard(D){
  const C=D.daily_check; if(!C) return "";
  const ET=iso=>aiWhen(iso);
  const icon={availability:"🩹",news:"📰",price:"£",rotation:"🔄"};
  const li=c=>`<li><span class="who">${esc(c.who)}</span> <span class="note">${esc(ET(c.at))}</span><div class="detail">${icon[c.kind]||""} ${esc(c.text)}</div></li>`;
  const now=(C.changes||[]).map(li).join("");
  const earlier=(C.history||[]).filter(c=>c.at!==C.checked_at).slice().reverse().slice(0,25).map(li).join("");
  return `<div class="card"><h2>Daily check</h2><ul class="note-list"><li>Last ran ${esc(ET(C.checked_at))} · watching ${C.watching} players (your squad and the AI team) for injuries, news, price moves and rotation risk</li><li>The program refreshes at least twice a day, more on match days</li></ul>${now?`<ul class="chiplist">${now}</ul>`:`<p class="note">Nothing new since the last check${C.previous_check?` (${esc(ET(C.previous_check))})`:""}.</p>`}${earlier?`<details class="fold"><summary><h3>Earlier changes</h3></summary><ul class="chiplist">${earlier}</ul></details>`:""}</div>`;
}
function aiChangesCard(A){
  if(!A) return "";
  const ch=(A.changes||[]).slice().reverse().slice(0,20);
  const icon={risk:"⚠️",swap:"🔁",captain:"©️","after-lock":"🔒"};
  const rows=ch.map(c=>`<li><span class="who">GW${c.gw} · ${esc(aiWhen(c.at))}</span><div class="detail">${icon[c.kind]||""} ${esc(c.text)}</div></li>`).join("");
  return `<div class="card"><h2>AI team · daily check</h2><ul class="note-list"><li>Re-checks every refresh (at least twice a day) for new injuries, doubts, reported rotation, fixture congestion and minutes that are falling, and re-picks if it helps — until it locks 12h before the deadline</li><li>Last checked ${esc(aiWhen(A.last_check))}. After the lock it can't change anything, but still flags news on locked players</li></ul>${rows?`<ul class="chiplist">${rows}</ul>`:`<p class="note">No changes to the plan yet.</p>`}</div>`;
}

// Chips tab: Free Hit / Wildcard player-for-player points, previous squad vs new squad (collapsed by default).
function chipCompareFold(c){
  if(!c||!(c.rows||[]).length) return "";
  const cell=x=>x?`${esc(x.name)} <b>${x.pts}</b>`:"–";
  const rows=c.rows.map(r=>`<tr class="${r.kept?"kept":""}"><td>${esc(r.pos)}</td><td>${cell(r.old)}</td><td>${cell(r.new)}</td></tr>`).join("");
  const d=c.new_total-c.old_total, b=c.new_best-c.old_best;
  return `<details class="fold"><summary><span class="foldsum">Player for player · ${c.old_total} vs ${c.new_total} (${sign(d)})</span></summary><table class="table-compact"><thead><tr><th style="width:16%">Pos</th><th style="width:42%">Before</th><th style="width:42%">After</th></tr></thead><tbody>${rows}<tr><td><b>All 15</b></td><td><b>${c.old_total}</b></td><td><b>${c.new_total}</b></td></tr><tr><td><b>Best XI</b></td><td><b>${c.old_best}</b></td><td><b>${c.new_best}</b></td></tr></tbody></table></details>`;
}

// ---- shared by index.html and bacalhau.html (moved out of the pages) ----
function paintTabs(){
  const g=TAB_GROUPS.find(x=>x.id===activeGroup)||TAB_GROUPS[0];
  const groups=TAB_GROUPS.map(x=>`<button class="group ${x.id===activeGroup?"on":""}" data-group="${x.id}" aria-pressed="${x.id===activeGroup}">${x.label}</button>`).join("");
  // A group with only one tab has nothing to switch between, so the pill row
  // is just a lone, oddly-small-looking button — skip it for single-tab
  // groups (e.g. Leagues) instead of rendering a selector with one option.
  const pills=g.tabs.length>1?`<div class="tab-pills">${g.tabs.map(([id,label])=>`<button class="${id===activeTab?"on":""}" data-id="${id}" aria-pressed="${id===activeTab}">${label}</button>`).join("")}</div>`:"";
  document.getElementById("tabs").innerHTML=`<div class="tab-groups">${groups}</div>${pills}`;
  document.querySelectorAll("section").forEach(s=>s.classList.toggle("on",s.id===activeTab));
  saveTab(TAB_KEY,activeTab);
}
function gwTable(){const rows=(D.gameweeks||[]).map(g=>{const chip=g.chip?` <span class="pill used">${esc(g.chip)}</span>`:"";return `<tr><td>GW${g.gw}${chip}</td><td><b>${g.points}</b></td><td>${g.field_avg??"-"}</td><td class="${cls(g.delta)}">${sign(g.delta)}</td><td>${g.bench}</td><td>${g.transfers}</td><td>${fmt(g.rank)}</td></tr>`;}).join("");return `<div class="card"><h2>Gameweek log</h2><div class="table-scroll"><table><thead><tr><th>GW</th><th>Pts</th><th>Field</th><th>d</th><th>Bench</th><th>Tr</th><th>OR</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;}
function chipClass(gw,name){const t=((D.bench_audit&&D.bench_audit[gw]&&D.bench_audit[gw].bench_tags)||{})[name];return t?"chip "+t:"chip sit";}
function bar(label,val,max,klass){const pct=Math.max(4,Math.round(100*val/Math.max(max,1)));return `<div class="barrow"><span>${label}</span><div class="track"><i class="${klass||""}" style="width:${pct}%"></i></div><b>${val}</b></div>`;}
// A Wildcard is permanent: the squad you kept after it against the one you held before it, gameweek by gameweek
// (chips.wildcard_running). Raw points of all 15 players, bench included, no captain multiplier.
function chipRunning(R){
  if(!R||!(R.rows||[]).length) return "";
  const rows=R.rows.map(r=>`<tr><td>GW${r.gw}</td><td>${r.old}</td><td>${r.new}</td><td class="${cls(r.diff)}">${sign(r.diff)}</td></tr>`).join("");
  return `<details class="fold"><summary>Since the Wildcard · <b class="${cls(R.diff)}">${sign(R.diff)}</b> over ${R.rows.length} GW${R.rows.length===1?"":"s"}</summary><p class="note">The 15 you held in GW${R.kept_gw} (kept unchanged) against the 15 you actually held each week, raw points, bench included, no captain multiplier.${R.hits?` Hits taken since: -${R.hits}.`:""}</p><table class="table-compact"><thead><tr><th>GW</th><th>Kept</th><th>Actual</th><th>Diff</th></tr></thead><tbody>${rows}<tr><td><b>Total</b></td><td><b>${R.old_total}</b></td><td><b>${R.new_total}</b></td><td class="${cls(R.diff)}"><b>${sign(R.diff)}</b></td></tr></tbody></table></details>`;
}
function chipRow(label,key){const gw=co[key];const used=gw!=null;const net=used&&CHIP_NET[key]?CHIP_NET[key].net:null;const note=used&&CHIP_NET[key]?CHIP_NET[key].note:"";return `<li><span class="who">${esc(label)}</span><span>${used?`<span class="pill used">Used GW${gw}</span>`:`<span class="pill free">Not used</span>`} ${used&&net!=null?`<b class="${net>=0?"pos":"neg"}">${sign(net)}</b> <span class="note">${esc((CHIP_NET[key]||{}).label||"")}</span>`:`<span class="note">—</span>`}</span><div class="detail">${used&&CHIP_NET[key]&&CHIP_NET[key].compare?chipCompareFold(CHIP_NET[key].compare):esc(used?(note||"Result not available yet."):"Still available.")}${used&&CHIP_NET[key]&&CHIP_NET[key].running?chipRunning(CHIP_NET[key].running):""}</div></li>`;}
function srcChips(list){return (list||[]).map(s=>`<span class="pill free">${esc(s)}</span>`).join(" ");}
function fhHead(A){
  const cn=(D.chip_net||{}).freehit;
  if(cn&&cn.net!=null) return `<p class="note">Net <b class="${cls(cn.net)}">${sign(cn.net)}</b> · the Free Hit squad against the one before it, player for player, bench included, no captain multiplier (same as the Chips tab)</p>${cn.compare?chipCompareFold(cn.compare):""}<p class="note">Lineups as actually played, with captain and auto-subs:</p>`;
  return `<p class="note">Net <b class="${cls(A.net)}">${sign(A.net)}</b></p><p class="note">${esc(A.why||"")}</p>`;
}

function benchBlock(key,title,open){
  const b=D.bench_audit&&D.bench_audit[key]; if(!b)return"";
  const max=Math.max(b.you,b.process,b.hindsight,1);
  const yours=(b.your_bench||[]).map(x=>`<div class="${chipClass(key,x[0])}">${esc(x[0])} · ${x[1]}</div>`).join("");
  const should=(b.better_bench||[]).map(x=>`<div class="chip ok">${esc(x[0])} · ${x[1]}</div>`).join("");
  // The first bar is the only judgment: green if the team matched/beat the
  // process benchmark (the best XI knowable pre-deadline), red if it fell
  // short of it. Process/Hindsight are reference lines, not verdicts — in
  // particular Hindsight is pure outcome (unknowable in advance), so coloring
  // it "bad" would imply it should have hit an unhittable target.
  const youKls=b.you>=b.process?"good":"bad";
  return `<details class="card fold"${open?" open":""}><summary><h2>${title}</h2><span class="foldsum"><b class="${youKls==="good"?"pos":"neg"}">${W.You} ${b.you}</b> · Process ${b.process} · Hindsight ${b.hindsight}</span></summary>${bar(W.You,b.you,max,"you")}${bar("Process",b.process,max,"proc")}${bar("Hindsight",b.hindsight,max,"hind")}<p class="note">${W.Your} bench</p><div class="xi">${yours}</div><p class="note">Should have benched</p><div class="xi">${should}</div></details>`;
}
function newsCard(title, vs){
  // Own/missing used to be one <li> per player with a full repeated sentence
  // ("X is heavily featured in GW6 coverage — mentioned by N/16 accounts.") —
  // readable for 1-2 names, but this squad-vs-consensus list routinely runs
  // to 8-9 players and that read as a wall of near-identical paragraphs. The
  // structured fields newsVsSquad already carries (mentions/tags) make a
  // table the same information in a fraction of the height.
  const tagTxt=tags=>(tags&&tags.length)?esc(tags.join(", ")):"–";
  const rowHtml=r=>`<tr><td>${nameCell(r.name,r.club)}</td><td>${r.mentions}</td><td>${tagTxt(r.tags)}</td></tr>`;
  const tblHead=`<thead><tr><th style="width:46%">Player</th><th style="width:18%">Mentions</th><th style="width:36%">Tags</th></tr></thead>`;
  const tbl=(rows,empty)=>rows.length?`<table class="table-compact">${tblHead}<tbody>${rows.map(rowHtml).join("")}</tbody></table>`:`<p class="note">${empty}</p>`;
  const fadeLi=vs.fade.length?vs.fade.map(raw=>{const x=esc(raw);return `<li><span class="who">${x.split(" · ")[0]}</span><div class="detail">${x.includes(" · ")?x.split(" · ").slice(1).join(" · "):x}</div></li>`;}).join(""):`<li><span class="note">No fade conflict.</span></li>`;
  const cap=vs.caps[0]?`<p class="note">Captain check: ${esc(vs.caps[0])}</p>`:"";
  return `<div class="card"><h2>${title}</h2><h3>Own and agreed</h3>${tbl(vs.owned,"None of the agreed names are in this squad.")}<h3>Missing and agreed</h3>${tbl(vs.missing,`${W.You} already own the agreed targets, or none were named.`)}<h3>Fade, but ${W.you} still start them</h3><ul class="chiplist">${fadeLi}</ul>${cap}</div>`;
}
function renderTargets(){
  const T=D.targets||{};
  const H=T.horizons||{};
  const scoreCls=s=>s>=5?"pos":s<0?"neg":"";
  const tgtHead=`<thead><tr><th style="width:24%">Player</th><th style="width:10%">Pos</th><th style="width:12%">Cost</th><th style="width:13%">Score</th><th style="width:11%">Top 50</th><th style="width:30%">Why</th></tr></thead>`;
  const buildCard=key=>{
    const h=H[key]||{};
    const n=h.horizon??Number(key);
    const rows=(h.top||[]).map(r=>`<tr><td>${nameCell(r.name,r.club)}</td><td>${esc(r.pos)}</td><td>£${r.cost.toFixed(1)}</td><td class="${scoreCls(r.score)}"><b>${r.score}</b></td><td>${r.elite_pct!=null?r.elite_pct+"%":"–"}</td><td style="white-space:normal">${esc((r.why||[]).join(" · ")||"–")}</td></tr>`).join("")||`<tr><td colspan="6"><span class="note">No qualifying players yet.</span></td></tr>`;
    return `<div class="card"><h2>Target · next ${n} GW${n===1?"":"s"}</h2><ul class="note-list"><li>League-wide shortlist combining Strategy tab signals (form, xGI/90, DEFCON, value, xG/xA regression) with Intel tab's News consensus</li><li>Score is a plain point count, not a hidden formula — see the Why column and legend below</li><li>Only players ${W.own} — everyone in the current squad is left out</li><li>Excludes anyone FPL itself flags as unavailable (${T.min_minutes??"?"}+ mins played to qualify)</li></ul><table class="table-compact">${tgtHead}<tbody>${rows}</tbody></table><ul class="legend-list"><li>In form = FPL form ≥6.0 (+2)</li><li>Strong xGI = xG+xA per 90 ≥0.5, non-GKP (+2)</li><li>Reliable DEFCON = clears the defensive-actions threshold for their position (+1)</li><li>Great value = top 25% points-per-£1m for their position (+1)</li><li>Due a return = underperforming their xGI by 2+ (buy-low signal) (+1) · Sell-high risk = overperforming their xGI by 2+ (-1)</li><li>Kind run = average fixture difficulty ≤2.6 over this horizon (+1)</li><li>News backed = tagged a transfer target in Intel coverage (+1) · Fade signal = tagged fade/sell or injury/doubt (-1)</li><li>Doubt = FPL flags a fitness doubt — shown, never scored</li></ul></div>`;
  };
  document.getElementById("target1").innerHTML=buildCard("1");
  document.getElementById("target3").innerHTML=buildCard("3");
  document.getElementById("target6").innerHTML=buildCard("6");
}

// ---- Intel tab renderers (shared). News themes carry FPL numbers from data.news_players (refresh.build_news_players).
function newsThemeRow(x,NP){
  const p=(NP||{})[String(x.id)]||null;
  const pills=p?`${p.yours?'<span class="pill used">Yours</span> ':''}${p.top2?'<span class="pill free">1st &amp; 2nd own</span> ':''}${p.status&&p.status!=="a"?`<span class="pill used">${esc(p.chance)}% fit</span> `:""}`:"";
  const nums=p?`<div class="detail note">${p.owned}% owned · £${Number(p.cost).toFixed(1)} · xP ${p.xp} · ${esc(p.fixture)}${p.news?` · ${esc(p.news)}`:""}</div>`:"";
  return `<li><span class="who">${esc(x.text)}</span>${pills?`<div class="detail">${pills}</div>`:""}${nums}<div class="detail">${srcChips(x.sources)}</div></li>`;
}
function renderNews(){
  const N=window.FPL_NEWS||D.news||{}, NP=D.news_players||{};
  const rank=(x)=>{const p=NP[String(x.id)]||{}; return [p.yours?0:1, -(x.sources||[]).length, -(p.owned||0)];};
  const order=(a,b)=>{const ra=rank(a), rb=rank(b); for(let i=0;i<3;i++) if(ra[i]!==rb[i]) return ra[i]-rb[i]; return 0;};
  const rows=list=>(list||[]).slice().sort(order).map(x=>newsThemeRow(x,NP)).join("");
  const agreed=rows(N.agreed)||`<li><span class="note">No 3-site overlap yet.</span></li>`;
  const split=rows(N.split)||`<li><span class="note">Nothing below the agreed threshold right now.</span></li>`;
  const links=(N.links||[]).map(x=>`<a href="${safeHref(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a>`).join(" · ");
  const fresh=N.new_articles||[];
  const rawCap=8;
  const newBlock=fresh.length?fresh.slice(0,rawCap).map(x=>`<li><span class="who">${esc(x.title)}</span><div class="detail"><span class="pill free">${esc(x.source)}</span> <a href="${safeHref(x.url)}" target="_blank" rel="noopener">open</a></div></li>`).join("")+(fresh.length>rawCap?`<li><span class="note">+${fresh.length-rawCap} more this scrape - already folded into the themes above.</span></li>`:""):`<li><span class="note">No new articles this scrape.</span></li>`;
  const sites=N.sites_checked?` · ${N.sites_with_articles??"?"} of ${N.sites_checked} sites had fresh articles`:"";
  document.getElementById("news").innerHTML=`${staleWarn(N,"news")}<div class="card"><h2>News · GW${N.gw||""}</h2>${freshnessMeta(N,"news")}<ul class="note-list"><li>Themes from title + article text${sites}</li><li>Emerging = 2 sites so far · Agreed = 3+ sites</li><li>Numbers beside each name are FPL's: ownership, price, the program's expected points and next fixture. Your players come first</li><li>Tags are checked against FPL: injury only if FPL flags the player, differential only under 15% owned</li></ul></div><div class="card"><h2>Agreed for GW${N.gw||""}</h2><ul class="chiplist">${agreed}</ul></div><div class="card"><h2>Emerging (2 sources)</h2><ul class="chiplist">${split}</ul></div><div class="card"><details><summary><h2 style="display:inline">New since last scrape (${fresh.length})</h2></summary><p class="note">Sources: ${links||"-"}</p><ul class="chiplist">${newBlock}</ul></details></div>`;
}
function renderTeamNews(){
  const T=D.team_news||{rows:[]};
  const rows=(T.rows||[]).map(r=>`<tr><td>${esc(r.name)} <span class="note">${esc(r.club)}</span>${r.yours?' <span class="pill used">Yours</span>':""}</td><td>${esc(r.pos)}</td><td>${r.chance==null?"–":r.chance+"%"}</td><td style="white-space:normal">${esc(r.news)}${r.returns?` <b>· back ${esc(r.returns)}</b>`:""}</td><td class="note">${esc(toToronto(r.added))}</td></tr>`).join("")||`<tr><td colspan="5"><span class="note">No FPL status changes in the last ${T.hours||72} hours.</span></td></tr>`;
  document.getElementById("teamNews").innerHTML=`<div class="card"><h2>Team news · last ${T.hours||72}h</h2><ul class="note-list"><li>FPL's own status changes, newest data first; your players first, then the most owned</li><li>Return dates are read from FPL's news line where it gives one${T.total>(T.rows||[]).length?` · showing ${(T.rows||[]).length} of ${T.total}`:""}</li></ul><table class="table-compact"><thead><tr><th style="width:26%">Player</th><th style="width:8%">Pos</th><th style="width:10%">Fit</th><th style="width:38%">News</th><th style="width:18%">Added</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function renderSetPieces(){
  const S=D.set_pieces||{rows:[]};
  const cell=l=>(l||[]).map(p=>`${esc(p.name)}${p.yours?" ★":""}`).join(", ")||"–";
  const rows=(S.rows||[]).map(r=>`<tr><td>${esc(r.club)}</td><td>${cell(r.pens)}</td><td>${cell(r.fks)}</td><td>${cell(r.corners)}</td></tr>`).join("");
  document.getElementById("setPieces").innerHTML=`<div class="card"><h2>Set-piece takers</h2><ul class="note-list"><li>First-choice taker per club from FPL's own order fields (★ = in your squad)</li></ul><table class="table-compact"><thead><tr><th style="width:12%">Club</th><th style="width:30%">Penalties</th><th style="width:29%">Free kicks</th><th style="width:29%">Corners</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
