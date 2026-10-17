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
function trendNote(gt, pronoun, gap){
  const subj=pronoun==="they"?"they":"you", obj=pronoun==="they"?"them":"you";
  if(gt==null) return null;
  if(gt===0) return "even with "+obj+" last GW";
  // gt = our last-GW points minus the rival's; gap > 0 = the rival is ahead, gap < 0 = the rival is behind
  if(gap!=null&&gap<0) return gt>0?subj+" stretched the lead by "+gt+" last GW":"they closed "+(-gt)+" last GW";
  return gt>0?subj+" closed "+gt+" last GW":"they gained "+(-gt)+" on "+obj+" last GW";
}
function rivalExtra(card, pronoun){
  if(!card) return "";
  const bits=[];
  const tn=trendNote(card.gap_trend, pronoun, card.gap); if(tn) bits.push(tn);
  if(card.chips_used&&card.chips_used.length) bits.push("used "+card.chips_used.join(", "));
  if(card.fixture) bits.push(card.fixture.label.toLowerCase()+" fixtures ("+card.fixture.avg_fdr+")");
  return bits.length?` <span class="note">— ${esc(bits.join(", "))}</span>`:"";
}
const NEWS_ALIAS=[["de cuyper","De Cuyper"],["decuyper","De Cuyper"],["joao pedro","João Pedro"],["joão pedro","João Pedro"],["szoboszlai","Szoboszlai"],["szobos","Szoboszlai"],["b.fernandes","B.Fernandes"],["fernandes","B.Fernandes"],["calvert-lewin","Calvert-Lewin"],["gakpo","Gakpo"],["isak","Isak"],["rogers","Rogers"],["palmer","Palmer"],["haaland","Haaland"],["wissa","Wissa"],["shaw","Shaw"],["gibbs-white","Gibbs-White"],["gibbs white","Gibbs-White"],["gvardiol","Gvardiol"],["saka","Saka"]];
function normTxt(s){return String(s||"").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"");}
function agreedPool(){const N=window.FPL_NEWS||{}; return (N.agreed||[]).map(x=>({text:x.text,from:"News",player:x.player,club:x.club,tags:x.tags,sources:x.sources,verdict:String(x.verdict||"").split(" (")[0],llm:(x.llm||{}).verdict}));}
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
    const p=D.plan||{};
    const tr=p.transfer&&p.transfer.move;
    const move=tr?esc(tr.out)+" → "+esc(tr.inn):"";
    const step=((D.planner||{}).steps||[])[0]||{};
    const capName=step.captain?esc(step.captain):"";
    const bits=["GW"+nd.gw];
    if(capName) bits.push("C "+capName);
    if(move) bits.push(move);
    el.innerHTML=`<span>${bits.join(" · ")}</span><b>${esc(fmtCountdown(ms))}</b>`;
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
    // classify on the structured verdict, not the text line (its count suffix says "1 captain, 1 fitness/rotation mentions")
    const v=it.llm||({"Leaning buy":"buy","Captain candidate":"captain","Leaning sell / avoid":"sell"})[it.verdict]||null;
    const isFade=it.player?(v==="sell"||v==="avoid"):/fade|sell into|sell /.test(t);
    const isCap=it.player?v==="captain":/captain/.test(t);
    const isIn=it.player?(v==="buy"||v==="captain"):/transfer in|to target|popular forward|priority/.test(t);
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
    const tn=trendNote(c.gap_trend,pronoun||"you",c.gap);
    const extra=[tn,c.fixture?c.fixture.label.toLowerCase()+" fixtures ("+c.fixture.avg_fdr+")":null].filter(Boolean);
    return `<li><span class="who">P${c.rank} · ${esc(c.name||"?")} · ${c.pts??"?"} (${gap})</span><div class="detail">${left}${used}${extra.length?` · ${esc(extra.join(", "))}`:""}</div></li>`;
  }).join("");
  return `<div class="card"><h2>Rivals that matter · ${esc(leagueName||"league")}</h2><ul class="note-list"><li>The managers closest to ${W.you==="they"?"them":"you"} on points (within 25, at least 3) — not simply 2nd, 3rd and last</li><li>"Chips left" = unused in the current half-season window; each chip comes back once per half</li></ul><ul class="chiplist">${rows}</ul>${tac.you_rank===1?`<p class="note">They can still chip a week ${W.you} cannot match. A −4 this half is a gift unless the incoming player is out for weeks.</p>`:""}</div>`;
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
  const effName=(b.effective&&b.effective!==b.captain[0])?b.effective:b.captain[0], effPts=(b.effective&&b.effective!==b.captain[0]&&b.mult)?Math.round(b.you/b.mult):b.captain[1];
  const why=[`${W.Your} captain: <b>${esc(effName)}</b> (${effPts} pts × ${b.mult} = ${b.you})${chipTag}`,
    `Process pick: <b>${esc(b.process_pick[0])}</b> — best points per appearance over the previous GWs${b.process_pick[2]>=0?` (${b.process_pick[2]})`:""}`,
    `Hindsight: <b>${esc(b.best[0])}</b> (${b.best[1]} pts) was the top scorer in ${W.Your.toLowerCase()} XI`].map(x=>`<li>${x}</li>`).join("")+eff;
  return `<details class="card fold"${open?" open":""}><summary><h2>${title}</h2><span class="foldsum"><b class="${good?"pos":"neg"}">${W.You} ${b.you}</b> · Process ${b.process} · Hindsight ${b.hindsight}</span></summary>${row("You",b.you,good?"good":"bad")}${row("Process",b.process)}${row("Hindsight",b.hindsight)}<ul class="why">${why}</ul><p class="note">Top scorers in your XI (C = captain, VC = vice, P = process pick)</p><div class="xi">${opts}</div></details>`;
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
    return `<tr><td>${esc(name)} <span class="note">${esc(club)}</span></td><td>${esc(pos)}</td><td><b>${pct}%</b></td><td>${mine.has(name)?`<span class="pill used">${W.You} own</span>`:'<span class="note">–</span>'}</td></tr>`;
  }).join("");
  const caps=Object.keys(E.cap||{}).sort((a,b)=>E.cap[b]-E.cap[a]).slice(0,5).map(id=>`${esc(((E.names||{})[id]||["?"])[0])} <b>${Math.round(100*E.cap[id]/E.n)}%</b>`).join(" · ");
  return `<div class="card"><h2>Elite ownership · ${esc(E.label||"")}</h2><ul class="note-list"><li>GW${E.gw} squads of the best managers in the overall table (FPL only publishes the first 50, so this is a small, elite sample)</li><li>Captains: ${caps||"–"}</li></ul><table class="table-compact"><thead><tr><th>Player</th><th>Pos</th><th>Top 50</th><th>${W.You}</th></tr></thead><tbody>${ownRows}</tbody></table></div>`;
}
// Multi-gameweek transfer plan (planner.py): the transfer path with the most expected points over the next few
// gameweeks, hits included, against simply rolling every week.
// Why a move was picked beyond expected points: the news / ownership / price / rivals signals behind it.
function shortReason(r){
  return String(r).replace(/^News \((\d+) sites\): (?:Claude: )?(\w+)/,"news: $2").replace(/^Top-\d+ own (\d+)%/,"top-50 $1%")
    .replace(/^only \d+\/\d+ rivals own him.*/,"differential").replace(/^\d+\/\d+ rivals own him \(covers.*/,"covers rivals")
    .replace(/^\d+\/\d+ rivals own him \(no gain.*/,"no gain on rivals").replace(/^differential adds risk.*/,"risky while leading")
    .replace(/^Takes (\w+)/,"$1").replace(/^Price likely to rise.*/,"price rise likely").replace(/^Price likely to fall.*/,"price fall likely")
    .replace(/^Price may rise.*/,"price may rise").replace(/^Price may fall.*/,"price may fall").replace(/^Price rising.*/,"price rising").replace(/^Price falling.*/,"price falling");
}
// Why a move was picked beyond expected points: one short line (top reasons for the player coming in), the rest folded.
function transferReasons(t){
  const inn=(t.reasons_in||[]), out=(t.reasons_out||[]);
  if(!inn.length&&!out.length) return "";
  const top=inn.slice(0,3).map(shortReason).join(" · ");
  const all=(inn.length>3||out.length)?`<details class="fold"><summary>All signals${t.adj?` (${t.adj>0?"+":""}${t.adj} pts)`:""}</summary><div class="note">In: ${esc(inn.map(shortReason).join(" · ")||"–")}<br>Out: ${esc(out.map(shortReason).join(" · ")||"–")}</div></details>`:"";
  return `${top?`<div class="detail note">Why: ${esc(top)}</div>`:""}${all}`;
}
function plannerCard(D){
  const P=D.planner||{}; if(!(P.steps||[]).length) return "";
  const rows=P.steps.map(s=>{
    const mv=(s.moves||[]).map(m=>`${esc(m.out)} → <b>${esc(m.in)}</b> <span class="note">${esc(m.pos)} · £${m.sell.toFixed(1)}→£${m.cost.toFixed(1)} · xP ${(m.xp_out||[])[0]??"–"}→${(m.xp_in||[])[0]??"–"}</span>${transferReasons({reasons_in:m.reasons_in,reasons_out:m.reasons_out,adj:m.adj})}`).join("<br>")||`<span class="note">Roll${s.ft_after!=null?" · "+s.ft_after+" FT banked":""}</span>`;
    return `<tr><td>GW${s.gw}</td><td style="white-space:normal">${mv}${s.hits?` <b class="neg">-${s.hits*4}</b>`:""}</td><td>${s.xp}</td><td>${esc(s.captain)}</td></tr>`;
  }).join("");
  const head=P.recommend==="follow"
    ?`Plan beats rolling by <b class="pos">+${P.gain}</b> expected points (model ${P.gain_model>=0?"+":""}${P.gain_model}, other signals ${P.gain_extra>=0?"+":""}${P.gain_extra})`
    :`Rolling is as good as any plan (best found ${sign(P.gain)}) - nothing is worth a move yet`;
  const first=(P.steps[0].moves||[]).length?`This week: ${P.steps[0].moves.map(m=>esc(m.out)+" → "+esc(m.in)).join(", ")}${P.steps[0].hits?` (−${4*P.steps[0].hits} hit)`:""}.`:"This week: roll.";
  return `<div class="card"><h2>Transfer planner · GW${P.gws[0]}-${P.gws[P.gws.length-1]}</h2><ul class="note-list"><li>${head}</li><li>${first} ${P.ft} FT, bank £${Number(P.bank).toFixed(1)}</li></ul><table class="table-compact"><thead><tr><th style="width:12%">GW</th><th style="width:46%">Move</th><th style="width:16%">xP</th><th style="width:26%">Captain</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
// Plan tab (both pages): one compact line per gameweek (moves + captain); prices, xP, reasons and team xP behind a per-row tap.
function plannerCardCompact(D){
  const P=D.planner||{}; if(!(P.steps||[]).length) return "";
  const rows=P.steps.map(s=>{
    const mv=(s.moves||[]);
    const line=mv.length?mv.map(m=>`${esc(m.out)} → <b>${esc(m.in)}</b>`).join(", "):`<span class="note">Roll${s.ft_after!=null?" · "+s.ft_after+" FT banked":""}</span>`;
    const hit=s.hits?` <b class="neg">−${s.hits*4}</b>`:"";
    const det=mv.map(m=>`<div class="plmove"><b>${esc(m.out)} → ${esc(m.in)}</b> <span class="note">${esc(m.pos)} · £${Number(m.sell).toFixed(1)}→£${Number(m.cost).toFixed(1)} · xP ${(m.xp_out||[])[0]??"–"}→${(m.xp_in||[])[0]??"–"}</span>${transferReasons({reasons_in:m.reasons_in,reasons_out:m.reasons_out,adj:m.adj})}</div>`).join("");
    return `<details class="plrow"><summary><span class="plgw">GW${s.gw}</span><span class="plline">${line}${hit} <span class="plcap">· C ${esc(s.captain)}</span></span></summary><div class="plbody">${det}<div class="note">Team xP ${s.xp}${s.ft_after!=null?" · "+s.ft_after+" FT after":""}${s.bank!=null?" · bank £"+Number(s.bank).toFixed(1):""}</div></div></details>`;
  }).join("");
  const head=P.recommend==="follow"
    ?`Plan beats rolling by <b class="pos">+${P.gain}</b> expected points (model ${P.gain_model>=0?"+":""}${P.gain_model}, other signals ${P.gain_extra>=0?"+":""}${P.gain_extra})`
    :`Rolling is as good as any plan (best found ${sign(P.gain)}) - nothing is worth a move yet`;
  const first=(P.steps[0].moves||[]).length?`This week: ${P.steps[0].moves.map(m=>esc(m.out)+" → "+esc(m.in)).join(", ")}${P.steps[0].hits?` (−${4*P.steps[0].hits} hit)`:""}.`:"This week: roll.";
  return `<div class="card"><h2>Transfer planner · GW${P.gws[0]}-${P.gws[P.gws.length-1]}</h2><ul class="note-list"><li>${head}</li><li>${first} ${P.ft} FT, bank £${Number(P.bank).toFixed(1)}</li><li>Tap a gameweek for positions, prices, xP and the reasons behind each move.</li></ul><div class="plrows">${rows}</div></div>`;
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
// Backtest of the expected-points model (calibrate.py): fitted on last season, graded on a later one it never saw.
function modelAccuracyCard(D){
  const M=D.model_accuracy||{}; const m=M.metrics||{}; if(!m.uncalibrated) return "";
  const row=(l,x)=>`<tr><td>${l}</td><td>${x.mae.toFixed(2)}</td><td>${x.rmse.toFixed(2)}</td><td>${x.pearson.toFixed(2)}</td><td>${x.spearman.toFixed(2)}</td></tr>`;
  return `<div class="card"><h2>How accurate is the model?</h2><ul class="note-list"><li>Expected points per player per gameweek vs what they scored: ${m.uncalibrated.n.toLocaleString()} player-gameweeks, ${esc(M.holdout||"")} (the model never saw them; fitted on ${esc(M.fitted_on||"")})</li><li>Lower error (MAE, RMSE) and higher correlation is better. Football is noisy: even a good model explains only a small part of one week's points</li></ul><table class="table-compact"><thead><tr><th style="width:40%">Predictor</th><th>MAE</th><th>RMSE</th><th>Pearson</th><th>Rank</th></tr></thead><tbody>${row("This model",m.uncalibrated)}${row("Season form (points per game)",m.form_baseline)}${row("Model + linear correction",m.calibrated)}</tbody></table><p class="note">The model is level with or slightly better than plain form. The linear correction barely helps, so it is not applied. Games with bookmaker odds also use the market's clean-sheet and goal expectations.</p></div>`;
}
function renderCaptain(D){
  const keys=Object.keys(D.captain_board||{}).sort((a,b)=>Number(a.replace(/\D/g,""))-Number(b.replace(/\D/g,""))).reverse();
  const legend=`<ul class="note-list"><li>You = the armband's actual return (captain points × multiplier; the vice if the captain didn't play)</li><li>Process = the starter with the best points per appearance over the previous 3 GWs — knowable at the deadline</li><li>Hindsight = the top scorer in your XI, which nobody can know in advance</li><li>Green You = matched or beat the process pick; red = fell short of it</li></ul>`;
  document.getElementById("captain").innerHTML=predLogCard(D)+modelAccuracyCard(D)+eliteCard(D)+(keys.length?keys.map((k,i)=>captainBlock(k,k.toUpperCase(),i===0,D)).join(""):`<div class="card"><h2>Captain audit</h2><p class="note">No finished GW captain audit yet.</p></div>`)+legend;
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
    ?`<div class="note">Starting squad built from scratch (free): £${P.squad_cost.toFixed(1)}m spent, £${P.bank.toFixed(1)}m in the bank</div>`
    :(P.transfers.length?P.transfers.map(t=>{
        const why=(t.reasons_in||[]).slice(0,4).map(r=>`<span class="pill free">${esc(shortReason(r))}</span>`).join(" ");
        const outWhy=(t.reasons_out||[]).length?`<div class="note">Selling: ${esc((t.reasons_out).map(shortReason).join(" · "))}</div>`:"";
        return `<div class="tmove"><div class="tm-top"><b>${esc(t.out)} → ${esc(t.in)}</b><span class="pos">+${t.gain} pts${t.hit?` <span class="neg">· −4 hit</span>`:""}</span></div><div class="note">£${(t.sell??0).toFixed(1)}m → £${(t.cost_in??0).toFixed(1)}m</div>${why?`<div class="tm-why">${why}</div>`:""}${outWhy}</div>`;}).join(""):`<div class="note">No transfers: rolls ${P.ft_before??0} free transfer${P.ft_before===1?"":"s"}</div>`);
  const chips=(A.chips_available||[]).length?`${(A.chips_available).map(c=>({wildcard:"Wildcard",freehit:"Free Hit",bboost:"Bench Boost","3xc":"Triple Captain"}[c]||c)).join(", ")} available (same as ${who||"you"}) — held, not played yet`:`No chips left (same as ${who||"you"})`;
  const why=P.squad.map(p=>`<li><span class="who">${esc(p.name)}</span><div class="detail">${esc(p.why||"")}</div></li>`).join("");
  return `<div class="card"><h2>AI team · GW${P.gw} plan ${pill}</h2><div class="aistats"><div><span>Locks</span><b>${esc(aiWhen(P.lock_at))}</b><small>deadline ${esc(aiWhen(P.deadline))}</small></div><div><span>Formation</span><b>${esc(P.formation)}</b><small>expected ${P.xp_xi} pts</small></div><div><span>Money</span><b>£${((P.sell_value??0)+(P.bank??0)).toFixed(1)}m</b><small>bank £${(P.bank??0).toFixed(1)}m</small></div></div>${(A.chips_available||[]).length?`<p class="note">Chips: ${esc(chips)}</p>`:""}<h3>Planned transfers · ${P.ft_before??0} free</h3>${moves}</div><div class="card"><h2>Starting XI · captain C, vice VC</h2><table class="table-compact">${head}<tbody>${xiRows}</tbody></table><h3>Bench (in auto-sub order)</h3><table class="table-compact">${head}<tbody>${benchRows}</tbody></table><details class="fold"><summary>How this works</summary><ul class="legend-list"><li>Started as a copy of ${who==="you"?"your":esc(who||"your")+"'s"} GW${A.cloned_from_gw??"?"} team (same players at the prices paid, bank, free transfers, chips and points) and plays independently from GW${A.start_gw??"?"} on</li><li>It makes its moves 12h before the deadline and shows them here before then</li><li>xP = expected points for GW${P.gw}: FPL's form/expected points, our xG/xA model, minutes security, the fixture and availability, plus Understat chance volume</li><li>Money follows FPL's rules: players are sold at their purchase price plus half of any profit (rounded down to 0.1m) and bought at today's price; prices are re-read every refresh and the buys lock in at the lock-time price</li><li>Squad score also weights the next gameweek's fixture so it avoids short-lived picks; transfers must beat a threshold (free moves +0.6, a −4 hit needs +5.5)</li></ul></details><details class="fold"><summary><h3>Why each pick</h3></summary><ul class="chiplist">${why}</ul></details></div>`;
}
function aiResultsCard(D,who){
  const A=D.ai_team; if(!A) return `<div class="card"><h2>AI team results</h2><p class="note">Nothing yet.</p></div>`;
  const H=Object.values(A.history||{}).sort((a,b)=>b.gw-a.gw);
  if(!H.length) return `<div class="card"><h2>AI team results</h2><p class="note" data-keep>It starts with the ${A.baseline_points??0} points you had at GW${A.cloned_from_gw??"?"}. GW${A.plan?A.plan.gw:7} is the first gameweek it plays on its own; points appear once that deadline passes.</p></div>`;
  const tot=A.season_points??A.total_points??0, you=A.user_season??A.user_total??0, W2=who||"You";
  let sel=H[0].gw; try{const k=Number(sessionStorage.getItem("lab:aigw")); if(H.some(h=>h.gw===k)) sel=k;}catch(e){}
  const p=H.find(h=>h.gw===sel)||H[0], r=p.result||{};
  const sq=Object.fromEntries((p.squad||[]).map(x=>[x.id,x]));
  const diff=(r.points??0)-(p.user_points??0);
  const when=A.generated_at?new Date(A.generated_at).toLocaleString("en-CA",{timeZone:"America/Toronto",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false})+" ET":"";
  const pills=H.map(h=>`<button type="button" data-aigw="${h.gw}" class="${h.gw===p.gw?"on":""}">GW${h.gw}${(h.result||{}).final?"":" ●"}</button>`).join("");
  const card=(l,isBench)=>{const x=sq[l.id]||{name:l.name,pos:l.pos,club:""};
    const isC=!isBench&&l.mult>1, isV=!isBench&&p.vice===l.id&&!isC&&r.captain&&r.captain!==l.name&&false;
    const pts=l.played?String(l.pts*(l.mult||1)):"–";
    const cls=!l.played?" yet":(l.pts>=6?" hot":l.pts<=1?" cold":"");
    return `<div class="lab-pk lab-rk${cls}" title="${esc(x.name)} ${esc(x.club||"")}: ${l.played?l.pts+" pts"+(l.mult>1?" ×"+l.mult:""):"yet to play / did not play"}"><span class="lab-bl">${isC?`<i class="b c">C</i>`:p.vice===l.id&&!isBench?`<i class="b v">V</i>`:""}</span>${labShirt(D,{club:x.club,pos:x.pos})}<span class="lab-pn${x.name.length>10?" long":""}">${esc(x.name)}</span><span class="lab-pf lab-pts">${pts}${isC&&l.played?` <small>×${l.mult}</small>`:""}</span></div>`;};
  const rows=["GKP","DEF","MID","FWD"].map(pos=>`<div class="lab-prow">${(r.lines||[]).filter(l=>l.pos===pos).map(l=>card(l,false)).join("")}</div>`).join("");
  const bench=(r.bench_lines||[]).map(l=>card(l,true)).join("");
  const subs=(r.autosubs||[]).length?`<p class="note">Auto-subs: ${(r.autosubs).map(s=>esc(s.out)+" → "+esc(s.in)).join(", ")}</p>`:"";
  const state=r.final?`<span class="pill used">Final</span>`:`<span class="pill free">Live · updating</span>`;
  return `<div class="card lab-aires"><h2>AI team results</h2>
    <div class="lab-rsum"><div><span>Season</span><b>AI ${tot}</b><small>${esc(W2)} ${you}</small></div><div><span>GW${p.gw}</span><b>${r.points??"–"}</b><small>${r.final&&p.user_points!=null?`${esc(W2)} ${p.user_points} · <i class="${diff>0?"pos":diff<0?"neg":""}">${(diff>0?"+":"")+diff}</i>`:`${esc(W2)} compared once settled`}</small></div><div><span>Bench</span><b>${r.bench_pts??0}</b><small>${r.hits?`−${r.hits} hit`:"no hit"}</small></div></div>
    <p class="note" data-keep>The AI started with the ${A.baseline_points??0} points you had at GW${A.cloned_from_gw??"?"}. ${state} ${when?`Data as of ${when}.`:""}${r.final?"":" Points show as each match is played; auto-subs and a vice-captain swap are only applied once the gameweek is settled."}</p>
    <div class="lab-stabs" id="labAiGw">${pills}</div>
    <div class="lab-pitch"><div class="lab-lines"><i class="box"></i><i class="six"></i><i class="half"></i><i class="circ"></i></div>${rows}</div>
    <div class="lab-bench">${bench}</div>${subs}</div>`;
}
function renderAiTeam(D,who){
  const a=document.getElementById("aiPlan"), r=document.getElementById("aiResults");
  const paint=()=>{ if(a) a.innerHTML=aiPlanCard(D,who)+aiChangesCard(D.ai_team); if(r) r.innerHTML=aiResultsCard(D,who); };
  paint();
  if(r&&!r.dataset.wired){
    r.dataset.wired="1";
    r.addEventListener("click",e=>{const b=e.target.closest("[data-aigw]"); if(!b) return; try{sessionStorage.setItem("lab:aigw",b.dataset.aigw);}catch(_){} paint();});
    // keep the results current while the page is open: re-read the data file every 5 minutes and repaint when the AI team moved
    const src=(document.querySelector('script[src*="data.js"]')||{}).src;
    if(src){ const url=src.split("?")[0]; let last=(D.ai_team||{}).generated_at;
      setInterval(async()=>{ try{ const t=await (await fetch(url+"?t="+Date.now(),{cache:"no-store"})).text(); const j=JSON.parse(t.slice(t.indexOf("{"),t.lastIndexOf("}")+1));
        if(j.ai_team&&j.ai_team.generated_at!==last){ last=j.ai_team.generated_at; D.ai_team=j.ai_team; if(j.generated_at) D.generated_at=j.generated_at; paint(); } }catch(_){} },5*60*1000); }
  }
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
  const icon={risk:"⚠️",swap:"🔁",transfer:"🔁",captain:"©️","after-lock":"🔒"};
  // Oldest first: group consecutive entries sharing the same check time (one refresh = one header).
  const groups=[];
  // Only what CHANGED is listed (the plan card above already says what the plan is): legacy per-player "swap" lines repeat the
  // plan and are dropped.
  (A.changes||[]).filter(c=>c.kind!=="swap").forEach(c=>{const g=groups[groups.length-1];if(g&&g.at===c.at&&g.gw===c.gw)g.items.push(c);else groups.push({at:c.at,gw:c.gw,items:[c]});});
  const key=g=>{const m=[];g.items.forEach(c=>{if(c.kind==="transfer")(c.moves||[]).forEach(x=>m.push(x.out+">"+x.in));});return m.sort().join("|");};
  // A->B->A: the middle check's transfers were undone by the check after it (render only).
  groups.forEach((g,i)=>{
    const k=key(g);
    if(i>=2&&k&&groups[i-2].gw===g.gw&&groups[i-1].gw===g.gw&&key(groups[i-2])===k){
      const mid=groups[i-1], km=key(mid);
      if(km&&km!==k) mid.items.forEach(c=>{if(c.kind==="transfer")c._rev=true;});
    }
  });
  const pill=t=>`<span style="display:inline-block;border-radius:999px;padding:1px 7px;font-size:11px;font-weight:600;background:rgba(128,128,128,.22);color:var(--muted,#999);white-space:nowrap">${esc(t)}</span>`;
  const line=c=>{
    let t=`${icon[c.kind]||""} ${esc(c.text)}`;
    if(c.kind==="transfer"){
      const cause=c.cause?pill(c.cause+(c.cause_ref?" · "+c.cause_ref:"")):"";
      if(c._rev) return `<div class="detail" style="opacity:.6"><s>${t}</s> ${cause} ${pill("reverted")}</div>`;
      t+=cause?" "+cause:"";
    }
    return `<div class="detail">${t}</div>`;
  };
  const rows=groups.slice().reverse().slice(0,5).map(g=>`<li><span class="who">GW${esc(g.gw)} · ${esc(aiWhen(g.at))}</span>${g.items.map(line).join("")}</li>`).join("")||`<li><span class="note">No changes since the plan was first made.</span></li>`;
  return `<div class="card"><h2>AI team · what changed</h2><p class="note">Checked ${esc(aiWhen(A.last_check))} · re-checks every refresh until it locks. Only changes are listed.</p><ul class="chiplist">${rows}</ul></div>`;
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
  return `<details class="card fold"${open?" open":""}><summary><h2>${title}</h2><span class="foldsum"><b class="${youKls==="good"?"pos":"neg"}">${W.You} ${b.you}</b> · Process ${b.process} · Hindsight ${b.hindsight}</span></summary>${bar(W.You,b.you,max,"you")}${bar("Process",b.process,max,"proc")}${bar("Hindsight",b.hindsight,max,"hind")}<p class="note">${W.Your} bench</p><div class="xi">${yours}</div><p class="note">Started, but the process XI would have left them out (judged on minutes before the deadline, not on points)</p><div class="xi">${should}</div></details>`;
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
  const tgtHead=`<thead><tr><th style="width:22%">Player</th><th style="width:9%">Pos</th><th style="width:11%">Cost</th><th style="width:13%">Score</th><th style="width:8%">xP</th><th style="width:12%">Top 50</th><th style="width:25%">Why</th></tr></thead>`;
  const buildCard=key=>{
    const h=H[key]||{};
    const n=h.horizon??Number(key);
    const whyPick=w=>{const arr=w||[], pref=["Reliable DEFCON","Due a return","Kind run"];const top=pref.filter(p=>arr.includes(p));const rest=arr.filter(x=>!top.includes(x)&&x!=="Sell-high risk"&&x!=="Great value"&&x!=="In form"&&x!=="Strong xGI");return (top.length?top:arr.filter(x=>x!=="Sell-high risk")).slice(0,2);};
    const sigPick=s=>{const arr=(s||[]).filter(x=>!/^Top-\d+ own/.test(x)&&!/rivals own/.test(x)&&!/^Price/.test(x));const news=arr.find(x=>/^News/.test(x));const set=arr.find(x=>/penalt|free kick|corner/i.test(x));return [news||set].filter(Boolean).slice(0,1);};
    const list=(h.top||[]).slice().sort((a,b)=>(b.score-a.score)||((b.xp??0)-(a.xp??0))).filter(r=>r.xp==null||r.xp/Math.max(1,n)>=2.5);
    const rows=list.map(r=>{const why=whyPick(r.why), sig=sigPick(r.sig);return `<tr><td>${nameCell(r.name,r.club)}</td><td>${esc(r.pos)}</td><td>£${r.cost.toFixed(1)}</td><td class="${scoreCls(r.score)}"><b>${r.score}</b></td><td>${r.xp!=null?r.xp:"–"}</td><td>${r.elite_pct!=null?r.elite_pct+"%":"–"}</td><td style="white-space:normal">${esc(why.join(" · ")||"–")}${sig.length?`<div class="note">${esc(sig.join(" · "))}</div>`:""}</td></tr>`;}).join("")||`<tr><td colspan="7"><span class="note">No qualifying players yet.</span></td></tr>`;
    const cards=list.map(r=>{const why=whyPick(r.why), sig=sigPick(r.sig);const sub=[...why,...sig].slice(0,2).join(" · ");return `<div class="tgt-card"><div class="tgt-main"><b>${esc(r.name)}</b><div class="tgt-meta"><span class="club">${esc(r.club)}</span> · ${esc(r.pos)}</div>${sub?`<div class="tgt-why">${esc(sub)}</div>`:""}</div><div class="tgt-price">£${r.cost.toFixed(1)}</div><div class="tgt-stat"><span>score</span><b class="${scoreCls(r.score)}">${r.score}</b></div><div class="tgt-stat"><span>xP</span><b>${r.xp!=null?r.xp:"–"}</b></div></div>`;}).join("")||`<div class="note">No qualifying players yet.</div>`;
    return `<div class="card"><h2>Target · next ${n} GW${n===1?"":"s"}</h2><div class="tgt-cards">${cards}</div><ul class="note-list"><li>League-wide shortlist combining Strategy tab signals (form, xGI/90, DEFCON, value, xG/xA regression) with Intel tab's News consensus</li><li>Score is a plain point count, not a hidden formula — see the Why column and legend below. xP is the program's expected points over the horizon (it already includes xG/xA, minutes, fixtures, rotation and fitness); the small grey line is news, top-50 ownership, price and rivals</li><li>Only players ${W.own} — everyone in the current squad is left out</li><li>Excludes anyone FPL itself flags as unavailable (${T.min_minutes??"?"}+ mins played to qualify)</li></ul><table class="table-compact tgt-table">${tgtHead}<tbody>${rows}</tbody></table><ul class="legend-list"><li>In form = FPL form ≥6.0 (+2)</li><li>Strong xGI = xG+xA per 90 ≥0.5, non-GKP (+2)</li><li>Reliable DEFCON = clears the defensive-actions threshold for their position (+1)</li><li>Great value = top 25% points-per-£1m for their position (+1)</li><li>Due a return = underperforming their xGI by 2+ (buy-low signal) (+1) · Sell-high risk = overperforming their xGI by 2+ (-1)</li><li>Kind run = average fixture difficulty ≤2.6 over this horizon (+1)</li><li>News backed = tagged a transfer target in Intel coverage (+1) · Fade signal = tagged fade/sell or injury/doubt (-1)</li><li>Doubt = FPL flags a fitness doubt — shown, never scored</li></ul></div>`;
  };
  document.getElementById("target1").innerHTML=buildCard("1");
  document.getElementById("target3").innerHTML=buildCard("3");
  document.getElementById("target6").innerHTML=buildCard("6");
}

// ---- Intel tab renderers (shared). News themes carry FPL numbers from data.news_players (refresh.build_news_players).
function newsThemeRow(x,NP){
  const p=(NP||{})[String(x.id)]||null;
  const TONE={good:{i:"🟢",l:"Good news",c:"pos"},bad:{i:"🔴",l:"Bad news",c:"neg"},mixed:{i:"🟠",l:"Mixed",c:""},neutral:{i:"⚪",l:"Neutral",c:""}};
  const T=TONE[x.tone]||TONE.neutral;
  const pills=p?`${p.yours?`<span class="pill used">${W.You==="You"?"Yours":"Theirs"}</span> `:''}${p.top2?'<span class="pill free">1st &amp; 2nd own</span> ':''}${p.status&&p.status!=="a"?`<span class="pill used">${esc(p.chance)}% fit</span> `:""}`:"";
  const nums=p?`<div class="detail note">${p.owned}% owned · £${Number(p.cost).toFixed(1)} · xP ${p.xp} · ${esc(p.fixture)}${p.news?` · ${esc(p.news)}`:""}</div>`:"";
  const L=x.llm; const VL={buy:"Buy",keep:"Keep",sell:"Sell",captain:"Captain",avoid:"Avoid",monitor:"Monitor",no_view:"No clear view"};
  const llmBlock=L?`<div class="detail"><span class="pill ${L.verdict==="buy"||L.verdict==="captain"?"used":"free"}">Claude: ${esc(VL[L.verdict]||L.verdict)}</span> <span class="note">${esc(L.confidence)} confidence</span><div>${esc(L.summary)}</div>${L.risks?`<div class="note">Risk: ${esc(L.risks)}</div>`:""}</div>`:"";
  // Point form: one short bullet per specific fact, split into good / bad news; neutral facts are folded.
  const TL={fitness:"fitness",role:"role",fixture:"fixture",form:"form",price:"price",captain:"captain"};
  const short=t=>{t=String(t).replace(/\s+/g," ").trim(); if(t.length<=150) return t; const cut=t.slice(0,150); const i=Math.max(cut.lastIndexOf(". "),cut.lastIndexOf(", "),cut.lastIndexOf(" "));return cut.slice(0,i>60?i:150)+"…";};
  const bullet=f=>`<li>${f.tone==="good"?"🟢":f.tone==="bad"?"🔴":"⚪"} <span class="note">${esc(TL[f.topic]||f.topic)}</span> ${esc(short(f.text))} ${f.url?`<a href="${safeHref(f.url)}" target="_blank" rel="noopener" title="${esc(f.title||"")}">${esc(f.source)}</a>`:`<span class="note">${esc(f.source)}</span>`}</li>`;
  const fl=(x.facts||[]), good=fl.filter(f=>f.tone==="good"), bad=fl.filter(f=>f.tone==="bad"), neu=fl.filter(f=>f.tone!=="good"&&f.tone!=="bad");
  const main=bad.concat(good);     // bad news first: it is what changes a decision
  const sayBlock=(main.length?`<ul class="chiplist facts">${main.map(bullet).join("")}</ul>`:"")+(neu.length?`<details class="fold"><summary>${neu.length} neutral</summary><ul class="chiplist facts">${neu.map(bullet).join("")}</ul></details>`:"");
  const sites=(x.sources||[]).length;
  return `<li><span class="who">${esc(x.player||"")} <span class="note">${esc(x.club||"")}</span> · ${T.i} <b class="${T.c}">${T.l}</b></span><div class="detail note">${sites} site${sites===1?"":"s"} · ${good.length} good · ${bad.length} bad · ${neu.length} neutral</div>${pills?`<div class="detail">${pills}</div>`:""}${nums}${llmBlock}${sayBlock}</li>`;
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
  document.getElementById("news").innerHTML=`${staleWarn(N,"news")}<div class="card"><h2>News · GW${N.gw||""}</h2>${freshnessMeta(N,"news")}<ul class="note-list"><li>Themes from title + article text${sites}</li><li>Each name gets a verdict from what the articles say about him (buy / keep / sell / captain / fitness), with the sentences behind it. Emerging = 2 sites · Agreed = 3+ sites</li><li>Numbers beside each name are FPL's: ownership, price, the program's expected points and next fixture. ${W.Your} players come first</li><li>Tags are checked against FPL: injury only if FPL flags the player, differential only under 15% owned</li></ul></div><div class="card"><h2>Agreed for GW${N.gw||""}</h2><ul class="chiplist">${agreed}</ul></div><div class="card"><h2>Emerging (2 sources)</h2><ul class="chiplist">${split}</ul></div><div class="card"><details><summary><h2 style="display:inline">New since last scrape (${fresh.length})</h2></summary><p class="note">Sources: ${links||"-"}</p><ul class="chiplist">${newBlock}</ul></details></div>`;
}
function renderSetPieces(){
  const S=D.set_pieces||{rows:[]};
  const cell=l=>(l||[]).map(p=>`${esc(p.name)}${p.yours?" ★":""}`).join(", ")||"–";
  const rows=(S.rows||[]).map(r=>`<tr><td>${esc(r.club)}</td><td>${cell(r.pens)}</td><td>${cell(r.fks)}</td><td>${cell(r.corners)}</td></tr>`).join("");
  document.getElementById("setPieces").innerHTML=`<div class="card"><h2>Set-piece takers</h2><ul class="note-list"><li>First-choice taker per club from FPL's own order fields (★ = in ${W.Your.toLowerCase()} squad)</li></ul><table class="table-compact"><thead><tr><th style="width:12%">Club</th><th style="width:30%">Penalties</th><th style="width:29%">Free kicks</th><th style="width:29%">Corners</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

// Scouting rows carry the model's xP and the extra signals behind them (ai_run.enrich_with_model).
function sigNote(r){ return r&&r.xp!=null?`<div class="note">xP ${r.xp}${(r.sig||[]).length?" · "+esc(r.sig.join(" · ")):""}</div>`:""; }

// Keep notes out of the way: explanatory lists and long notes sit behind a small "i" toggle (idempotent, runs after every render).
(function(){
  let busy=false;
  const LONG=70;
  function wrap(el){
    const d=document.createElement("details");d.className="more";
    const s=document.createElement("summary");s.textContent="ⓘ";d.appendChild(s);
    el.parentNode.insertBefore(d,el);d.appendChild(el);
  }
  function minimize(){
    if(busy)return;busy=true;
    try{
      document.querySelectorAll("section .legend-list, section .note-list, section p.note").forEach(el=>{
        if(el.closest("details.more")||el.closest("table")||el.dataset.keep!==undefined)return;
        const isList=el.matches(".legend-list,.note-list");
        if(!isList&&(el.textContent||"").trim().length<LONG)return;
        wrap(el);
      });
    }catch(e){}
    busy=false;
  }
  function start(){minimize();new MutationObserver(minimize).observe(document.body,{childList:true,subtree:true});}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);else start();
})();

// ============================================================================================
// FPL Lab app shell (2026-10 redesign): PLAN / TARGET / MORE. Shared by index.html and bacalhau.html.
// The existing renderers still fill their <section>s exactly as before; the shell builds the two new
// views from the same data and moves every old section, untouched, into MORE so no feature is lost.
// ============================================================================================
const LAB_CLUB={ARS:"Arsenal",AVL:"Aston Villa",BHA:"Brighton",BOU:"Bournemouth",BRE:"Brentford",BUR:"Burnley",CHE:"Chelsea",COV:"Coventry",CRY:"Crystal Palace",EVE:"Everton",FUL:"Fulham",HUL:"Hull",IPS:"Ipswich",LEE:"Leeds",LEI:"Leicester",LIV:"Liverpool",MCI:"Man City",MUN:"Man Utd",NEW:"Newcastle",NFO:"Nott'm Forest",SOU:"Southampton",SUN:"Sunderland",TOT:"Spurs",WHU:"West Ham",WOL:"Wolves"};
const LAB_SVG={
  flask:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3"/><path d="M7.5 15h9"/></svg>',
  info:'<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9.5"/><path d="M12 11v6M12 7.5v.01"/></svg>',
  plan:'<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M8.5 10h7M8.5 14h7M8.5 18h4"/></svg>',
  target:'<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="3"/><path d="M12 1.5v3M12 19.5v3M1.5 12h3M19.5 12h3"/></svg>',
  more:'<svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  shield:'<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M12 2.5 4 5.5v6c0 5 3.4 8.6 8 10 4.6-1.4 8-5 8-10v-6z"/><text x="12" y="15.6" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor" stroke="none" font-family="-apple-system,sans-serif">C</text></svg>',
  swap:'<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 3.5V8h4.5"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20.5V16h-4.5"/></svg>',
  chev:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
  left:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 5-7 7 7 7"/></svg>',
  right:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>',
  cal:'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
  refresh:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 3.5V8h4.5M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20.5V16h-4.5"/></svg>',
  dots:'<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>',
  bolt:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
  aim:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/></svg>',
  star:'<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="m12 2.8 2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.2l-5.6 3 1.1-6.3L2.9 9.5l6.3-.9z"/></svg>',
  guard:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 2.5 4 5.5v6c0 5 3.4 8.6 8 10 4.6-1.4 8-5 8-10v-6z"/></svg>',
  pound:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M17 20H7c2-2 2.5-4 2.5-6.5V8.5a3.5 3.5 0 0 1 6.6-1.6M6.5 13h7"/></svg>',
  flag:'<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 21V4M5 4h11l-2 4 2 4H5"/></svg>'
};
const LAB_POSC={GKP:"#f5b83d",DEF:"#a78bfa",MID:"#4ade80",FWD:"#fb923c"};
function labNum(v,d){return v==null||v===""||isNaN(Number(v))?"–":Number(v).toFixed(d);}
// "Today, 7:03 PM" / "Yesterday, ..." / "Wed, Oct 14, ..." in Toronto time
function labWhen(s){
  const m=String(s||"").match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/); if(!m) return esc(s||"–");
  const d=new Date(m[1]+"T"+m[2]+":00Z"); if(isNaN(+d)) return esc(s);
  const day=x=>new Intl.DateTimeFormat("en-CA",{timeZone:TZ}).format(x);
  const t=new Intl.DateTimeFormat("en-US",{timeZone:TZ,hour:"numeric",minute:"2-digit",hour12:true}).format(d);
  const now=new Date(), y=new Date(Date.now()-864e5);
  if(day(d)===day(now)) return "Today, "+t;
  if(day(d)===day(y)) return "Yesterday, "+t;
  return new Intl.DateTimeFormat("en-US",{timeZone:TZ,weekday:"short",month:"short",day:"numeric"}).format(d)+", "+t;
}
function labMyNames(D){return new Set(((D.plan||{}).rows||[]).map(r=>r[1]));}
// ---------------------------------------------------------------- PLAN view
function labCaptainPanel(D,they){
  const xi=((D.plan||{}).xis||{})["gw"+((D.deadline||{}).next_gw)]||{};
  const strip=n=>String(n||"").replace(/\s*\((?:C|VC)\)$/,"");
  const cap=strip((xi.xi||[]).find(n=>/\(C\)$/.test(n)))||((D.planner||{}).steps||[{}])[0].captain||"–";
  const vc=strip((xi.xi||[]).find(n=>/\(VC\)$/.test(n)))||"–";
  const fx={}; ((D.plan||{}).rows||[]).forEach(r=>{fx[r[1]]=r[3];});
  const xp0=(D.planner||{}).xp0||{};
  const starters=new Set((xi.xi||[]).map(strip));
  const ranked=Object.keys(xp0).filter(n=>!starters.size||starters.has(n)).sort((a,b)=>xp0[b]-xp0[a]).slice(0,5);
  const rows=ranked.map((n,i)=>`<tr><td>${i+1}. ${esc(n)}${n===cap?' <span class="lab-pill c">C</span>':n===vc?' <span class="lab-pill vc">VC</span>':""}</td><td class="note">${esc(fx[n]||"")}</td><td><b>${labNum(xp0[n],1)}</b></td></tr>`).join("");
  const ai=(D.ai_team||{}).plan||{}; const aiName=id=>((ai.squad||[]).find(p=>p.id===id)||{}).name;
  return {cap,vc,html:`<p class="note">Captain = the highest expected points (xP) in ${they?"their":"your"} starting XI this gameweek; the vice is the next best from a different club.</p><table class="lab-tbl"><thead><tr><th>Player</th><th>Next</th><th>xP</th></tr></thead><tbody>${rows||'<tr><td colspan="3" class="note">No expected points yet.</td></tr>'}</tbody></table>${ai.captain?`<p class="note">AI team (plays on its own): C ${esc(aiName(ai.captain)||"?")} · VC ${esc(aiName(ai.vice)||"?")}</p>`:""}`};
}
function labTransfer(D){
  const P=D.planner||{}, s0=(P.steps||[])[0]||{}, mv=s0.moves||[];
  const ft=P.ft??(D.strategy||{}).free_transfers??"?";
  const names=mv.length?mv.map(m=>`${esc(m.out)} → <strong>${esc(m.in)}</strong>`).join("<br>")+(s0.hits?` <span class="neg">−${4*s0.hits}</span>`:""):"Roll: bank the transfer";
  return {ft,names};
}
function labChips(D,they){
  const S=(D.strategy||{}).chips||[]; const nxt=(D.deadline||{}).next_gw||0;
  const rows=S.map(c=>{
    const w=(c.windows||[]); const cur=w.find(x=>nxt>=x.start&&nxt<=x.stop)||w[0]||{}; const later=w.find(x=>x.start>nxt);
    let st;
    if(cur.used_gw) st=`<span class="lab-pill used">Used GW${cur.used_gw}</span>${later?` <span class="note">next from GW${later.start}</span>`:""}`;
    else st=`<span class="lab-pill ok">Available</span> <span class="note">until GW${cur.stop}</span>`;
    return `<li><b>${esc(c.label||c.chip)}</b><span>${st}</span></li>`;
  }).join("");
  return `<ul class="lab-list">${rows||'<li class="note">No chip data.</li>'}</ul><p class="note">Full chip history and strategy: More › Review › Chips and More › Strategy › Chips &amp; Hits.</p>`;
}
function labLeague(D,they){
  const L=D.leagues||{}, out=[];
  for(const lg of (L.mini||[])){
    const t=lg.table||[]; const me=t.find(r=>r.me);
    const keep=t.filter((r,i)=>i<5||r.me);
    const rows=keep.map(r=>`<tr class="${r.me?"lab-me":""}"><td>${r.rank}</td><td>${esc(r.team)}${r.me?(they?" · them":" · you"):""}</td><td><b>${r.pts}</b></td></tr>`).join("");
    const T=lg.tactics||{};
    const rk=(x,d)=>x&&x.rank?"P"+x.rank:d;
    const diffs=(T.you_unique||[]).map(x=>`<span class="chip ok">${esc(x.name)} · ${x.own}%${x.vs_a?" vs "+rk(T.first,"1st"):""}${x.vs_b?" vs "+rk(T.second,"2nd"):""}</span>`).join("");
    const share=(T.they_share||[]).map(x=>`<span class="chip sit">${esc(x.name)} · ${x.count}/${x.n}</span>`).join("");
    const gap=T.gap_to_first;
    out.push(`<div class="lab-lg"><h3>${esc(lg.name)} <span class="note">· ${me?"P"+me.rank:"–"} of ${lg.size||t.length}${gap!=null&&gap>0?" · "+gap+" behind P1":gap!=null&&gap<0?" · "+(-gap)+" ahead":""}</span></h3><table class="lab-tbl"><thead><tr><th>#</th><th>Team</th><th>Pts</th></tr></thead><tbody>${rows}</tbody></table>${T.first?`<p class="note">${rk(T.first,"1st")}: <b>${esc(T.first.name)}</b> ${T.first.pts}${rivalExtra(T.first,they?"they":"you")}<br>${T.second?`${rk(T.second,"2nd")}: <b>${esc(T.second.name)}</b> ${T.second.pts}${rivalExtra(T.second,they?"they":"you")}`:""}</p>`:""}${diffs?`<p class="note">${they?"Their":"Your"} differentials vs the rivals above</p><div class="xi">${diffs}</div>`:""}${share?`<p class="note">Both rivals own, ${they?"they don't":"you don't"}</p><div class="xi">${share}</div>`:""}</div>`);
  }
  return (out.join("")||'<p class="note">No mini-league data yet.</p>')+'<p class="note">Locked squads, ownership and the full rival breakdown: More › Leagues.</p>';
}
function labNews(D,they){
  const mine=labMyNames(D); const av=(D.plan||{}).availability||{};
  const flags=Object.keys(av).map(n=>`<li><b>${esc(n)}</b> <span class="lab-pill ${av[n].kind==="out"?"bad":"warn"}">${esc(av[n].label||av[n].status)}</span><div class="note">${esc(av[n].news||"")}</div></li>`).join("");
  const tn=((D.team_news||{}).rows||[]).slice(0,6).map(r=>`<li><b>${esc(r.name)}</b> <span class="note">${esc(r.club)}</span> <span class="lab-pill ${r.status==="d"?"warn":"bad"}">${r.status==="d"?"DOUBT "+(r.chance??""):r.status==="s"?"SUS":r.status==="u"?"OUT":"INJ"}</span>${mine.has(r.name)?' <span class="lab-pill used">'+(they?"theirs":"yours")+'</span>':""}<div class="note">${esc(r.news||"")}</div></li>`).join("");
  const N=window.FPL_NEWS||{};
  const ag=(N.agreed||[]).slice(0,6).map(x=>`<li><b>${esc(x.player||"")}</b> <span class="note">${esc(x.club||"")}</span> · ${esc(x.verdict||"")}<div class="note">${(x.sources||[]).length} sites: ${esc((x.sources||[]).join(", "))}</div></li>`).join("");
  return `<h3>${they?"Their":"Your"} squad</h3><ul class="lab-list col">${flags||`<li class="note">No injury or suspension flags in ${they?"their":"your"} squad.</li>`}</ul><h3>New FPL flags · last ${(D.team_news||{}).hours||72}h</h3><ul class="lab-list col">${tn||'<li class="note">No new flags.</li>'}</ul><h3>What the FPL sites agree on${N.gw?" · GW"+N.gw:""}</h3><ul class="lab-list col">${ag||'<li class="note">No agreed themes yet.</li>'}</ul><p class="note">Full news, injuries, rotation, price radar and set pieces: More › Intel.</p>`;
}
// ---------------------------------------------------------------- PREDICTIONS (data.predictions, ai_run.build_predictions)
function labPred(D){
  const P=D.predictions||{}; if(!P.gw) return `<p class="note">Predictions appear on the next refresh.</p>`;
  const R=P.record||{}, CAT=[["goals","Goals"],["assists","Assists"],["clean_sheets","Clean sheets"],["defcon","DEFCON"]];
  const row=(name,club,val,sub,mark)=>`<div class="lab-pr"><span class="n">${mark?`<i class="lab-ok ${mark}">${mark==="y"?"✓":"✗"}</i> `:""}${esc(name)}${club?` <em>${esc(club)}</em>`:""}</span><span class="v">${val}</span>${sub?`<span class="s">${sub}</span>`:""}</div>`;
  const sec=(t,items,sub)=>`<h3 class="lab-ph3">${t}</h3>${sub?`<p class="note lab-pnote2">${sub}</p>`:""}<div class="lab-prs">${items.join("")||'<p class="note">Nothing to show yet.</p>'}</div>`;
  const pc=(h,n)=>n?Math.round(100*h/n):null;
  // track record
  let rec="";
  if(R.graded){
    const [h,n]=R.overall||[0,0];
    const cal=R.calibration||{};
    const cats=CAT.map(([k,l])=>{const t=(R.total||{})[k]||[0,0]; return `<div class="lab-rc"><span>${l}</span><b>${pc(t[0],t[1])??"–"}%</b><em>${t[0]}/${t[1]}</em></div>`;}).join("");
    const gwRows=(R.per_gw||[]).slice().reverse().map(r=>`<tr><td>GW${r.gw}</td>${CAT.map(([k])=>`<td>${r[k][0]}/${r[k][1]}</td>`).join("")}</tr>`).join("");
    const calLines=CAT.map(([k,l])=>{const c=cal[k]||{}; if(!c.n) return ""; const s=c.scale; return `<li><b>${l}</b>: predicted ${c.mean_p}% on average, came in at ${c.hit_rate}% (${c.n} picks) · ${c.n>=30?(s===1?"no correction needed":`probabilities now ×${s}`):"collecting data before correcting"}</li>`;}).join("");
    const whyLines=CAT.map(([k,l])=>{const w=(R.why||{})[k]||[]; if(!w.length) return ""; return `<li><b>${l}</b> misses: ${w.slice(0,3).map(([t,c])=>`${esc(t)} (${c})`).join(" · ")}</li>`;}).join("");
    rec=`<div class="lab-rec"><h3 class="lab-ph3">Track record · ${R.graded} gameweek${R.graded===1?"":"s"} graded</h3>
      <div class="lab-rbig"><b>${pc(h,n)}%</b><span>of ${n} top-10 picks came off (${h})</span></div>
      <div class="lab-rcs">${cats}</div>
      <table class="lab-rtab"><thead><tr><th>GW</th>${CAT.map(([,l])=>`<th>${l.replace("Clean sheets","CS")}</th>`).join("")}</tr></thead><tbody>${gwRows}</tbody></table>
      ${calLines?`<h4 class="lab-ph4">Recalibration</h4><ul class="lab-rl">${calLines}</ul>`:""}
      ${whyLines?`<h4 class="lab-ph4">Why picks missed</h4><ul class="lab-rl">${whyLines}</ul>`:""}</div>`;
  } else {
    rec=`<p class="note" data-keep>Track record starts once GW${esc(String((R.pending||[P.gw])[0]||P.gw))} is settled: each top-10 is saved before the deadline, marked right or wrong against FPL's final stats, and any bias is corrected in later predictions.</p>`;
  }
  // earlier method: the saved chance-volume goal / assist lists and DEFCON top-10s from before this box existed
  let leg="";
  const LG=R.legacy;
  if(LG&&((LG.goals_assists||[]).length||(LG.defcon||[]).length)){
    const gws=[...new Set([...(LG.goals_assists||[]).map(r=>r.gw),...(LG.defcon||[]).map(r=>r.gw)])].sort((x,y)=>y-x);
    const ga=Object.fromEntries((LG.goals_assists||[]).map(r=>[r.gw,r])), dc=Object.fromEntries((LG.defcon||[]).map(r=>[r.gw,r]));
    const cell=v=>v&&v[1]?`${v[0]}/${v[1]}`:"–";
    const T=LG.total||{}, tp=v=>v&&v[1]?`${v[0]}/${v[1]} (${Math.round(100*v[0]/v[1])}%)`:"–";
    leg=`<div class="lab-rec"><h3 class="lab-ph3">Earlier method · saved before these predictions</h3>
      <p class="lab-rl2"><b>Goals</b> ${tp(T.goals)} · <b>Assists</b> ${tp(T.assists)} · <b>DEFCON</b> ${tp(T.defcon)}</p>
      <table class="lab-rtab"><thead><tr><th>GW</th><th>Goals</th><th>Assists</th><th>DEFCON</th></tr></thead><tbody>${gws.map(g=>`<tr><td>GW${g}${ga[g]&&ga[g].rebuilt?"*":""}</td><td>${cell((ga[g]||{}).goals)}</td><td>${cell((ga[g]||{}).assists)}</td><td>${cell((dc[g]||{}).defcon)}</td></tr>`).join("")}</tbody></table>
      <p class="note">The old chance-volume goal and assist lists and the DEFCON top-10s the program saved (only players who played count). * the goal and assist lists for that week were rebuilt afterwards, not saved at the time. Kept apart from the new hit rate and from the recalibration.${(LG.pending||[]).length?` GW${LG.pending.join(", GW")} will be graded when settled.`:""}</p></div>`;
  }
  const lists=sec("Goals",(P.goals||[]).map(r=>row(r.name,r.club,`<b>${r.p}%</b>`,`${esc(r.fixture)} · ${labNum(r.xg,2)} xG`)),"Chance of at least one goal")
   +sec("Assists",(P.assists||[]).map(r=>row(r.name,r.club,`<b>${r.p}%</b>`,`${esc(r.fixture)} · ${labNum(r.xa,2)} xA`)),"Chance of at least one assist")
   +sec("Clean sheets",(P.clean_sheets||[]).map(r=>row(r.club,"",`<b>${r.p}%</b>`,`${esc(r.fixture)} · ${esc((r.who||[]).join(", "))}`)),"Chance the club concedes none")
   +sec("DEFCON",(P.defcon||[]).map(r=>row(r.name,r.club,`<b>${r.p}%</b>`,`${esc(r.fixture)} · ${esc(r.pos)}`)),"Chance of reaching the defensive-contribution bonus")
   +sec("Rotation",(P.rotation||[]).map(r=>row(r.name,r.club,`<b>${r.rotate??(100-r.start)}%</b>`,esc((r.why||[])[0]||""))),"Chance of rotation (not graded)");
  const L=R.last;
  const lastBlock=L?`<h3 class="lab-ph3">How GW${L.gw} went</h3>`+CAT.map(([k,l])=>`<h4 class="lab-ph4">${l}</h4><div class="lab-prs">${((L.picks||{})[k]||[]).map(p=>row(p.name||p.club,p.name?p.club:"",`<b>${p.p}%</b>`,esc(p.why||""),p.hit?"y":"n")).join("")}</div>`).join(""):"";
  return `<p class="note" data-keep>GW${P.gw} from the program's own model (xG/xA, minutes, fixtures, news).</p>`+rec+leg+lists+lastBlock;
}
function labAcc(id,title,sub,body){
  return `<details class="lab-acc" id="${id}"><summary><div><b>${title}</b><span>${sub}</span></div><i>${LAB_SVG.chev}</i></summary><div class="lab-acc-body">${body}</div></details>`;
}
// ---------------------------------------------------------------- TARGET view
function labPool(D,h){
  const mine=labMyNames(D), out=new Set();
  ((D.injury_watch||{}).rows||[]).forEach(r=>{if(/INJ|SUS|OUT|LEFT/.test(r.label||"")) out.add(r.name+"|"+r.club);});
  ((D.team_news||{}).rows||[]).forEach(r=>{if(r.status!=="d") out.add(r.name+"|"+r.club);});
  Object.values(D.news_players||{}).forEach(r=>{if(["i","s","u"].includes(r.status)) out.add(r.name+"|"+r.club);});
  const M=new Map();
  const add=(r,f)=>{ if(!r||!r.name) return; const k=r.name+"|"+(r.club||""); if(mine.has(r.name)||out.has(k)) return;
    const p=M.get(k)||{name:r.name,club:r.club,pos:r.pos||(D.pos_by_name||{})[r.name]};
    f(p,r); if(r.cost!=null) p.cost=r.cost; if(r.owned_pct!=null) p.owned=r.owned_pct; if(!p.pos&&r.pos) p.pos=r.pos; M.set(k,p); };
  const H=(D.targets||{}).horizons||{};
  Object.keys(H).forEach(k=>(H[k].top||[]).forEach(r=>add(r,(p,r)=>{p.form=r.form; p.xgi90=r.xgi_p90; if(k===String(h)){p.xp=r.xp; p.fdr=r.fdr; p.why=r.why; p.sig=r.sig; p.ov=true;}})));
  const T=(H[String(h)]||{}).top||[];
  const X=D.xg_signal||{};
  ["top","top_over","top_under","notable"].forEach(k=>(X[k]||[]).forEach(r=>add(r,(p,r)=>{p.xg=r.xg; p.xgi=r.xgi; p.xgi90=r.xgi_p90; p.goals=r.goals; p.assists=r.assists; p.next=r.next; if(p.fdr==null&&h===1) p.fdr=r.fdr;})));
  (X.top_def_lucky||[]).forEach(r=>add(r,(p,r)=>{p.xgc=r.xgc; p.gc=r.goals_conceded; p.next=r.next; p.mins=r.minutes;}));
  ((D.defcon||{}).top||[]).forEach(r=>add(r,(p,r)=>{p.dc90=r.per90; p.dcthr=r.threshold;}));
  const byPos=(o,f)=>Object.values((o||{}).by_pos||{}).forEach(list=>(list||[]).forEach(r=>add(r,f)));
  byPos(D.form_fdr,(p,r)=>{p.form=p.form??r.form; p.next=p.next||r.fixture; if(h===1&&p.fdr==null) p.fdr=r.fdr;});
  byPos(D.value_board,(p,r)=>{p.vpm=r.value_per_1m; p.pts=r.points;});
  Object.values((D.form_fdr||{}).by_pos||{}).forEach(()=>{});
  const tt=D.transfer_targets||{}; ["xg","defcon"].forEach(k=>(tt[k]||[]).forEach(r=>add(r,(p,r)=>{if(p.xp==null&&h===1) p.xp=r.xp; p.sig=p.sig||r.sig;})));
  ((D.set_pieces||{}).rows||[]).forEach(c=>{[["pens","Pens"],["fks","FKs"],["corners","Corners"]].forEach(([k,l])=>(c[k]||[]).forEach(t=>{ if(t.yours) return; add({name:t.name,club:c.club,owned_pct:t.owned},(p)=>{p.sp=(p.sp||[]); if(!p.sp.includes(l)) p.sp.push(l);}); }));});
  const order=new Map(T.map((r,i)=>[r.name+"|"+r.club,i]));
  const list=[...M.values()]; list.forEach(p=>{p.ord=order.has(p.name+"|"+p.club)?order.get(p.name+"|"+p.club):999;});
  return list;
}
const LAB_FILTERS=[
  {id:"overview",label:"Overview",note:"The Target shortlist for this horizon: form, xGI, value, fixtures and news combined, best first.",pick:p=>p.ov,sort:(a,b)=>a.ord-b.ord,head:(p,n)=>[LAB_SVG.bolt,`${labNum(p.xp,1)} xP next ${n} GW${n>1?"s":""}`]},
  {id:"attack",label:"Attack",note:"Forwards by expected goals this season.",pick:p=>p.pos==="FWD"&&(p.xg!=null||p.xgi90!=null),sort:(a,b)=>(b.xg??b.xgi90??0)-(a.xg??a.xgi90??0),head:p=>[LAB_SVG.aim,p.xg!=null?`${labNum(p.xg,1)} xG this season`:`${labNum(p.xgi90,2)} xGI per 90`]},
  {id:"midfield",label:"Midfield",note:"Midfielders by expected goal involvement per 90.",pick:p=>p.pos==="MID"&&p.xgi90!=null,sort:(a,b)=>b.xgi90-a.xgi90,head:p=>[LAB_SVG.star,`${labNum(p.xgi90,2)} xGI per 90`]},
  {id:"defence",label:"Defence",note:"Defenders and keepers: defensive contributions per 90 (DEFCON) and expected points.",pick:p=>p.pos==="DEF"||p.pos==="GKP",sort:(a,b)=>(b.dc90??-1)-(a.dc90??-1)||(b.xp??0)-(a.xp??0),head:p=>[LAB_SVG.guard,p.dc90!=null?`${labNum(p.dc90,1)} def. actions per 90 (needs ${p.dcthr})`:p.xgc!=null?`${labNum(p.xgc,1)} xGC this season`:`${labNum(p.xp,1)} xP`]},
  {id:"setpieces",label:"Set Pieces",note:"First-choice penalty, free-kick and corner takers (FPL's own order).",pick:p=>(p.sp||[]).length,sort:(a,b)=>(b.sp.includes("Pens")-a.sp.includes("Pens"))||(b.xgi90??0)-(a.xgi90??0),head:p=>[LAB_SVG.flag,p.sp.join(" · ")]},
  {id:"form",label:"Form",note:"FPL form: average points over the last 30 days.",pick:p=>p.form!=null,sort:(a,b)=>b.form-a.form,head:p=>[LAB_SVG.bolt,`${labNum(p.form,1)} form (pts per game, 30 days)`]},
  {id:"xgi",label:"xGI",note:"Expected goal involvement per 90 minutes, this season.",pick:p=>p.xgi90!=null&&p.pos!=="GKP",sort:(a,b)=>b.xgi90-a.xgi90,head:p=>[LAB_SVG.star,`${labNum(p.xgi90,2)} xGI per 90`]},
  {id:"xgc",label:"xGC",note:"Defences conceding fewer goals than their expected goals conceded (xGC): good so far, but luck can turn.",pick:p=>p.xgc!=null,sort:(a,b)=>(b.xgc-b.gc)-(a.xgc-a.gc),head:p=>[LAB_SVG.guard,`${labNum(p.xgc,1)} xGC · ${p.gc} conceded`]},
  {id:"bonus",label:"Bonus",note:"The site's data has no bonus-point totals yet, so this sorts by expected points (xP), which already includes expected bonus.",pick:p=>p.xp!=null,sort:(a,b)=>b.xp-a.xp,head:(p,n)=>[LAB_SVG.star,`${labNum(p.xp,1)} xP next ${n} GW${n>1?"s":""}`]},
  {id:"fixtures",label:"Fixtures",note:"Easiest fixtures first: average FPL difficulty (FDR) over the horizon.",pick:p=>p.fdr!=null,sort:(a,b)=>a.fdr-b.fdr||(b.xp??0)-(a.xp??0),head:(p,n)=>[LAB_SVG.cal,`FDR ${labNum(p.fdr,1)} next ${n} GW${n>1?"s":""}`]},
  {id:"value",label:"Value",note:"Season points per £1m, best in each position.",pick:p=>p.vpm!=null,sort:(a,b)=>b.vpm-a.vpm,head:p=>[LAB_SVG.pound,`${labNum(p.vpm,1)} pts per £1m (${p.pts} pts)`]}
];
function labCard(p,f,n,i){
  const [ic,txt]=f.head(p,n); const pc=LAB_POSC[p.pos]||"#8b95a1";
  const big=p.pos==="FWD"&&p.xg!=null?["xG",labNum(p.xg,1)]:["xGI per 90",labNum(p.xgi90,2)];
  const more=[...(p.why||[]),...(p.sig||[]).map(s=>typeof shortReason==="function"?shortReason(s):s)];
  return `<div class="lab-pc"><div class="lab-pc-h"><i class="dot" style="background:${pc}"></i><b>${esc(p.name)}</b><button class="lab-dots" aria-label="More about ${esc(p.name)}" data-i="${i}">${LAB_SVG.dots}</button></div><div class="lab-pc-c">${esc(LAB_CLUB[p.club]||p.club||"")} • <span style="color:${pc};font-weight:700">${esc(p.pos||"")}</span></div><div class="lab-pc-s"><span style="color:${pc}">${ic}</span>${esc(txt)}</div><div class="lab-pc-g"><div><span>Form</span><b>${labNum(p.form,1)}</b></div><div><span>xP</span><b>${labNum(p.xp,1)}</b></div><div><span>${big[0]}</span><b>${big[1]}</b></div><div><span>Price</span><b class="lab-green">£${labNum(p.cost,1)}m</b></div></div><div class="lab-pc-x" hidden>${p.next?`<div>Next: ${esc(p.next)}</div>`:""}${p.owned!=null?`<div>Owned ${p.owned}% overall</div>`:""}${more.length?`<div>${esc(more.join(" · "))}</div>`:""}</div></div>`;
}
function labTargetView(D,el,they){
  const H=Object.keys((D.targets||{}).horizons||{}).map(Number).sort((a,b)=>a-b); if(!H.length){el.innerHTML='<div class="card"><p class="note">No target data yet.</p></div>';return;}
  let hi=0, fid="overview";
  const g0=(D.deadline||{}).next_gw||1;
  const paint=()=>{
    const n=H[hi], f=LAB_FILTERS.find(x=>x.id===fid);
    const pool=labPool(D,n).filter(f.pick).sort(f.sort).slice(0,20);
    const label=n===1?`GW ${g0}`:`GW ${g0}–${g0+n-1}`;
    el.innerHTML=`<div class="lab-gw"><button data-d="-1" ${hi===0?"disabled":""} aria-label="Shorter horizon">${LAB_SVG.left}</button><div><b><span class="lab-blue">${LAB_SVG.cal}</span>${label}</b><span>Next ${n} gameweek${n>1?"s":""} · 2026/27 season</span></div><button data-d="1" ${hi===H.length-1?"disabled":""} aria-label="Longer horizon">${LAB_SVG.right}</button></div><div class="lab-filters">${LAB_FILTERS.map(x=>`<button class="${x.id===fid?"on":""}" data-f="${x.id}">${x.label}</button>`).join("")}</div><p class="note lab-fnote">${esc(f.note)} Players ${they?"Bacalhau owns":"you own"} and injured players are left out.</p><div class="lab-grid">${pool.map((p,i)=>labCard(p,f,n,i)).join("")||'<p class="note">No players for this filter.</p>'}</div><div class="lab-end"><span>–</span> End of targets</div>`;
  };
  el.addEventListener("click",e=>{
    const b=e.target.closest("button"); if(!b) return;
    if(b.dataset.d){hi=Math.max(0,Math.min(H.length-1,hi+Number(b.dataset.d))); paint();}
    else if(b.dataset.f){fid=b.dataset.f; paint();}
    else if(b.classList.contains("lab-dots")){const x=b.closest(".lab-pc").querySelector(".lab-pc-x"); x.hidden=!x.hidden; b.classList.toggle("on",!x.hidden);}
  });
  paint();
}
// ---------------------------------------------------------------- PLAN: pitch view
// FPL team codes (shirt images); data.js carries team_codes from refresh.py, this is the fallback
const LAB_TCODE={ARS:3,AVL:7,BOU:91,BRE:94,BHA:36,CHE:8,COV:9,CRY:31,EVE:11,FUL:54,HUL:88,IPS:40,LEE:2,LIV:14,MCI:43,MUN:1,NEW:4,NFO:17,TOT:6,SUN:56,BUR:90,WHU:21,WOL:39,LEI:13,SOU:20};
const LAB_KIT={ARS:"#db0007",AVL:"#7b003a",BOU:"#d71920",BRE:"#e30613",BHA:"#0057b8",CHE:"#034694",COV:"#5ab4e5",CRY:"#1b458f",EVE:"#003399",FUL:"#f2f2f2",HUL:"#f5a12d",IPS:"#0044a9",LEE:"#f2f2f2",LIV:"#c8102e",MCI:"#6cabdd",MUN:"#da291c",NEW:"#241f20",NFO:"#dd0000",TOT:"#f2f2f2",SUN:"#eb172b",BUR:"#6c1d45",WHU:"#7a263a",WOL:"#fdb913",LEI:"#003090",SOU:"#d71920"};
function labFix(s){ // "A NFO" -> "NFO (A)"; "H EVE, A ARS" -> "EVE (H), ARS (A)"
  s=String(s||"").trim(); if(!s) return "–";
  return s.split(/\s*[,+&]\s*/).map(x=>{const m=x.match(/^([HA])\s+(\w+)$/); return m?`${m[2]} (${m[1]})`:x;}).join(", ");
}
function labAvail(D,name){
  const a=((D.plan||{}).availability||{})[name]; if(a) return a;
  const t=(((D.team_news||{}).rows)||[]).find(r=>r.name===name); if(t) return {status:t.status,chance:t.chance,news:t.news};
  const w=(((D.injury_watch||{}).rows)||[]).find(r=>r.name===name); if(w) return {status:w.status,chance:w.chance,news:w.label};
  return null;
}
// best legal XI (same rule as ai_team.pick_xi): 1 GK, 3 DEF / 2 MID / 1 FWD minimum, then best xP up to 5/5/3
function labPickXI(players){
  const MIN={DEF:3,MID:2,FWD:1}, MAX={DEF:5,MID:5,FWD:3};
  const by=p=>players.filter(x=>x.pos===p).sort((a,b)=>b.xp-a.xp);
  const xi=[by("GKP")[0]].filter(Boolean), cnt={DEF:0,MID:0,FWD:0};
  for(const p of ["DEF","MID","FWD"]) by(p).slice(0,MIN[p]).forEach(x=>{xi.push(x);cnt[p]++;});
  players.filter(x=>x.pos!=="GKP"&&!xi.includes(x)).sort((a,b)=>b.xp-a.xp).forEach(x=>{if(xi.length<11&&cnt[x.pos]<MAX[x.pos]){xi.push(x);cnt[x.pos]++;}});
  const bench=by("GKP").slice(1).concat(players.filter(x=>x.pos!=="GKP"&&!xi.includes(x)).sort((a,b)=>b.xp-a.xp));
  return {xi,bench};
}
function labSquads(D){
  const P=D.plan||{}, PL=D.planner||{}, xp0=PL.xp0||{}, s0=(PL.steps||[])[0]||{};
  const gw=(D.deadline||{}).next_gw||P.next_gw;
  const strip=n=>String(n||"").replace(/\s*\((?:C|VC)\)$/,"");
  const cur=(P.rows||[]).map(r=>({name:r[1],pos:r[0],club:r[2],fix:labFix(r[3]),xp:Number(xp0[r[1]]??0)}));
  const lx=(P.xis||{})["gw"+gw]||{};
  // CURRENT: the squad as it stands, lineup and armband as the Plan tab shows them
  const byN=n=>cur.find(p=>p.name===n);
  let current=null;
  if((lx.xi||[]).length===11){
    current={xi:lx.xi.map(strip).map(byN).filter(Boolean),bench:(lx.bench||[]).map(byN).filter(Boolean),
      cap:strip(lx.xi.find(n=>/\(C\)$/.test(n))),vc:strip(lx.xi.find(n=>/\(VC\)$/.test(n)))};
  } else { const k=labPickXI(cur); const r=k.xi.slice().sort((a,b)=>b.xp-a.xp); current={...k,cap:(r[0]||{}).name,vc:(r[1]||{}).name}; }
  // RECOMMENDED: the planner's moves for this GW applied, XI and bench re-picked on expected points
  const moves=s0.moves||[], outs=new Set(moves.map(m=>m.out));
  const rec=cur.filter(p=>!outs.has(p.name)).concat(moves.map(m=>({name:m.in,pos:m.pos||(D.pos_by_name||{})[m.in],club:m.in_club,fix:m.fix_in||"–",xp:Number((m.xp_in||[])[0]??0),inn:true})));
  let recommended=null;
  if(rec.length===15){
    const k=labPickXI(rec); const r=k.xi.slice().sort((a,b)=>b.xp-a.xp);
    const cap=(s0.captain&&k.xi.some(p=>p.name===s0.captain))?s0.captain:(r[0]||{}).name;
    const vc=(current.vc&&current.vc!==cap&&k.xi.some(p=>p.name===current.vc))?current.vc:(r.find(p=>p.name!==cap)||{}).name;
    recommended={...k,cap,vc,moves,hits:s0.hits||0};
  }
  // AI: the AI team's own plan for the same gameweek (ai_team.plan), shown the same way
  let ai=null; const AP=(D.ai_team||{}).plan;
  if(AP&&AP.gw===gw&&(AP.xi||[]).length===11){
    const sq={}; (AP.squad||[]).forEach(p=>{sq[p.id]=p;});
    const ins=new Set((AP.transfers||[]).map(t=>t.in));
    const mk=id=>{const p=sq[id]; return p?{name:p.name,pos:p.pos,club:p.club,fix:labFix(p.fixture),xp:Number(p.xp||0),inn:ins.has(p.name)}:null;};
    const xi=AP.xi.map(mk).filter(Boolean), bench=(AP.bench||[]).map(mk).filter(Boolean);
    if(xi.length===11) ai={xi,bench,cap:(sq[AP.captain]||{}).name,vc:(sq[AP.vice]||{}).name,moves:(AP.transfers||[]).map(t=>({out:t.out,in:t.in})),hits:AP.hits||0,locked:!!AP.locked};
  }
  return {gw,current,recommended,ai};
}
function labShirt(D,p){
  const code=((D.team_codes||{})[p.club])??LAB_TCODE[p.club];
  const kit=LAB_KIT[p.club]||"#64748b";
  const img=code!=null?`<img src="https://fantasy.premierleague.com/dist/img/shirts/standard/shirt_${code}${p.pos==="GKP"?"_1":""}-110.webp" alt="" loading="lazy" onerror="this.parentNode.classList.add('noimg');this.remove()">`:"";
  return `<span class="lab-shirt${img?"":" noimg"}" style="--kit:${kit}">${img}</span>`;
}
function labPCard(D,p,team,star,label){
  const a=labAvail(D,p.name);
  const ch=a&&a.chance!=null?Number(a.chance):null;
  const out=a&&(ch===0||/^[isun]$/.test(a.status||"")||/^(out|inj|sus|left)/i.test(a.status||""));
  const doubt=a&&!out&&(a.status==="d"||/doubt/i.test(a.status||"")||(ch!=null&&ch<100));
  const cls=out?" out":doubt?" doubt":"";
  const tip=[p.name,p.club,p.fix,"xP "+labNum(p.xp,1),a&&a.news?a.news:(a&&ch!=null?ch+"% chance":"")].filter(Boolean).join(" · ");
  const bl=[p.name===team.cap?'<i class="b c">C</i>':p.name===team.vc?'<i class="b v">V</i>':"",p.inn?'<i class="b in">IN</i>':""].join("");
  const br=[out?`<i class="b warn out" title="${esc(a.news||"Out")}">✕</i>`:doubt?`<i class="b warn" title="${esc(a.news||"Doubtful")}">⚠</i>`:"",star?'<i class="b star" title="Top-3 expected points in the XI">★</i>':""].join("");
  return `<div class="lab-pk${cls}" title="${esc(tip)}">${label?`<span class="lab-pl">${esc(label)}</span>`:""}<span class="lab-bl">${bl}</span><span class="lab-br">${br}</span>${labShirt(D,p)}<span class="lab-pn${p.name.length>10?" long":""}">${esc(p.name)}</span><span class="lab-pf">${esc(p.fix||"–")}${ch!=null&&ch<100?` · ${ch}%`:""}</span></div>`;
}
function labPitchHtml(D,team,they){
  if(!team) return `<p class="note">No lineup yet.</p>`;
  const top3=new Set(team.xi.slice().sort((a,b)=>b.xp-a.xp).slice(0,3).map(p=>p.name));
  const rows=["GKP","DEF","MID","FWD"].map(pos=>`<div class="lab-prow">${team.xi.filter(p=>p.pos===pos).sort((a,b)=>b.xp-a.xp).map(p=>labPCard(D,p,team,top3.has(p.name))).join("")}</div>`).join("");
  const bench=team.bench.map(p=>labPCard(D,p,team,false,p.pos)).join("");
  return `<div class="lab-pitch"><div class="lab-lines"><i class="box"></i><i class="six"></i><i class="half"></i><i class="circ"></i></div>${rows}</div><div class="lab-bench">${bench}</div>${team.hits?`<p class="note lab-pnote">These moves cost a <span class="neg">−${4*team.hits}</span> hit.</p>`:""}`;
}
function labPitch(D,they,KEY){
  const S=labSquads(D); if(!S.current) return "";
  const MODES=[["cur","Current",S.current],["rec","Recommended",S.recommended],["ai","AI",S.ai]].filter(m=>m[2]);
  const k=KEY+":pitch"; let mode=(()=>{try{return localStorage.getItem(k)}catch(e){return null}})()||"rec";
  if(!MODES.some(m=>m[0]===mode)) mode=MODES[0][0];
  const mv=t=>(t.moves||[]).map(x=>esc(x.out)+" → "+esc(x.in)).join(", ")||"none";
  const sub=m=>m==="rec"?`${they?"Their":"Your"} squad after the planned move${(S.recommended.moves||[]).length===1?"":"s"} (${mv(S.recommended)}), XI, bench and armband by expected points.`
    :m==="ai"?`The AI team's own plan (${mv(S.ai)}) ${S.ai.locked?"- locked.":"- can still change until it locks."}`
    :`${they?"Their":"Your"} squad as it stands now, with the Plan lineup and armband.`;
  const teamOf=m=>m==="rec"?S.recommended:m==="ai"?S.ai:S.current;
  const legend=`<p class="note lab-legend"><i class="b c">C</i> captain <i class="b v">V</i> vice <i class="b in">IN</i> planned transfer in <i class="b star">★</i> top-3 xP <i class="b warn">⚠</i> doubtful <i class="b warn out">✕</i> out</p>`;
  const html=`<div class="lab-pitchcard card" id="labPitch"><div class="lab-ph"><h2>GW${S.gw} TEAM</h2>${MODES.length>1?`<div class="lab-seg" role="tablist">${MODES.map(m=>`<button data-pm="${m[0]}">${m[1]}</button>`).join("")}</div>`:""}</div><p class="note lab-psub"></p><div class="lab-pbody"></div>${legend}</div>`;
  setTimeout(()=>{
    const el=document.getElementById("labPitch"); if(!el) return;
    const paint=()=>{ el.querySelector(".lab-psub").innerHTML=sub(mode); el.querySelector(".lab-pbody").innerHTML=labPitchHtml(D,teamOf(mode),they);
      el.querySelectorAll("[data-pm]").forEach(b=>{b.classList.toggle("on",b.dataset.pm===mode);b.setAttribute("aria-selected",b.dataset.pm===mode);}); };
    el.addEventListener("click",e=>{const b=e.target.closest("[data-pm]"); if(!b) return; mode=b.dataset.pm; try{localStorage.setItem(k,mode)}catch(_){} paint();});
    paint();
  },0);
  return html;
}
// ---------------------------------------------------------------- Decision log (rec_log.py)
function labSigned(n){n=Number(n)||0; return n>0?"+"+n:n<0?"−"+(-n):"0";}
function labVerdict(s,they){ if(!s) return ""; const d=s.diff; const who=they?"They":"You";
  return d>0?`<span class="lab-v you">${who} +${d}</span>`:d<0?`<span class="lab-v model">Model +${-d}</span>`:`<span class="lab-v same">Same</span>`; }
const LAB_CHIPN={wildcard:"Wildcard",freehit:"Free Hit",bboost:"Bench Boost","3xc":"Triple Captain",manager:"Assistant Manager"};
function labDecLast(D,they){
  const L=D.decision_log||{}; const r=(L.rows||[]).find(x=>x.status==="scored"); if(!r) return "";
  const s=r.score, ok=s.diff>=0;
  return `<button class="lab-last" data-declog="gw${r.gw}"><span>Last GW${r.gw}: <b>${they?"They":"You"} ${s.you}</b> vs <b>Model ${s.model}</b> ${ok?'<i class="ok">✓</i>':'<i class="bad">✗</i>'}</span><span class="note">Decision log ›</span></button>`;
}
function labDecRow(r,they){
  const Y=they?"They":"You", y=they?"their":"your";
  const mv=t=>(t||[]).length?(t||[]).map(m=>`${esc(m.out)} → ${esc(m.in)}`).join(", "):"Roll";
  const meta=`<p class="note">Saved ${esc(r.saved_at_et||"?")}${r.code_sha?` · code ${esc(String(r.code_sha).slice(0,7))}`:""}${r.backfilled?` · <b>backfilled</b>: ${esc(r.backfill_note||"")}`:""}</p>`;
  if(r.status!=="scored"){
    const body=`<ul class="lab-dl"><li><span>Model transfers</span><b>${mv(r.transfers)}${r.hit_cost?` <span class="neg">−${r.hit_cost}</span>`:""}</b></li><li><span>Model captain / vice</span><b>${esc(r.captain_name||"–")} / ${esc(r.vice_name||"–")}</b></li>${r.xp!=null?`<li><span>Model xP (XI, captain doubled, net of hits)</span><b>${labNum(r.xp,1)}</b></li>`:""}<li><span>Chip</span><b>${r.chip?esc(LAB_CHIPN[r.chip]||r.chip):"None planned"}</b></li></ul>${meta}`;
    return `<details class="lab-drow pending" id="declog-gw${r.gw}"><summary><span class="lab-dgw">GW${r.gw}</span><span class="lab-dmain"><b>${r.status==="frozen"?"Recommendation frozen at the deadline":"Recommendation saved"}</b><span class="note">scored after GW finishes · C ${esc(r.captain_name||"–")} · ${mv(r.transfers)}</span></span><i>${LAB_SVG.chev}</i></summary>${body}</details>`;
  }
  const s=r.score, C=s.captain||{}, T=s.transfers||{}, Ln=s.lineup||{};
  const tl=(arr,hits)=>((arr||[]).length?(arr||[]).map(t=>`<li><span>${esc(t.out)} (${t.out_pts}) → ${esc(t.in)} (${t.in_pts})</span><b class="${t.net>0?"pos":t.net<0?"neg":""}">${labSigned(t.net)}</b></li>`).join(""):`<li><span class="note">No transfers</span><b>0</b></li>`)+(hits?`<li><span>Hits</span><b class="neg">−${hits}</b></li>`:"");
  const subs=a=>(a||[]).length?(a||[]).map(x=>`${esc(x.out)}→${esc(x.in)}`).join(", "):"none";
  const chipY=(s.chip||{}).you;
  const body=`<div class="lab-dsec"><h4>Captain <span>${labSigned(C.diff)}</span></h4><ul class="lab-dl"><li><span>${Y}: ${esc(C.you||"–")} ${C.you_pts}×${C.you_mult}</span><b>${C.you_pts*C.you_mult}</b></li><li><span>Model: ${esc(C.model||"–")} ${C.model_pts}×${C.model_mult}</span><b>${C.model_pts*C.model_mult}</b></li></ul></div>
<div class="lab-dsec"><h4>Transfers <span>${labSigned(T.diff)}</span></h4><p class="note">${Y} (in − out this GW, net of hits: ${labSigned(T.you_net)})${chipY&&/wildcard|freehit/.test(chipY)?` · ${esc(LAB_CHIPN[chipY])} week: net change from the previous squad`:""}</p><ul class="lab-dl">${tl(T.you,T.you_hits)}</ul><p class="note">Model (net ${labSigned(T.model_net)})</p><ul class="lab-dl">${tl(T.model,T.model_hits)}</ul></div>
<div class="lab-dsec"><h4>Lineup, bench &amp; chips <span>${labSigned(Ln.diff)}</span></h4><p class="note">The rest of the gap: XI and bench picks, autosubs${chipY?`, ${y} ${esc(LAB_CHIPN[chipY]||chipY)}`:""}. Bench points: ${Y.toLowerCase()} ${Ln.you_bench_pts} · model ${Ln.model_bench_pts}. Model autosubs: ${subs(Ln.model_autosubs)}.</p></div>${meta}`;
  return `<details class="lab-drow" id="declog-gw${r.gw}"><summary><span class="lab-dgw">GW${r.gw}</span><span class="lab-dmain"><span class="lab-dsc">${Y} <b>${s.you}</b> · Model <b>${s.model}</b> ${labVerdict(s,they)}${r.backfilled?' <span class="lab-pill used">backfilled</span>':""}</span><span class="note">C ${esc(C.you||"–")} / ${esc(C.model||"–")} · T ${(T.you||[]).length?(T.you.length>2?T.you.length+" moves":mv(T.you)):"roll"}${chipY?" ("+esc(LAB_CHIPN[chipY]||chipY)+")":""} / ${mv(T.model)}</span></span><i>${LAB_SVG.chev}</i></summary>${body}</details>`;
}
function labDecLog(D,they){
  const L=D.decision_log||{}, rows=L.rows||[], t=L.totals||{}; const Y=they?"They":"You";
  if(!rows.length) return `<p class="note">No recommendations saved yet. The next refresh before a deadline saves one.</p>`;
  const dc=t.decisions||{}; const dl=k=>{const x=dc[k]||{};return `<li><span>${k[0].toUpperCase()+k.slice(1)}</span><b>${x.you||0} / ${x.model||0} / ${x.same||0}</b></li>`;};
  const top=t.gws?`<div class="lab-dtot"><div><span class="note">Season · ${t.gws} GW${t.gws===1?"":"s"} scored</span><b>${Y} ${t.you} · Model ${t.model}</b>${labVerdict({diff:t.diff},they)}</div><p class="note">Gameweeks won: ${Y.toLowerCase()} ${t.you_wins} · model ${t.model_wins} · same ${t.same}</p><ul class="lab-dl"><li><span class="note">Decisions won (${Y.toLowerCase()} / model / same)</span><b></b></li>${dl("captain")}${dl("transfers")}${dl("lineup")}</ul></div>`:"";
  return `${top}<p class="note">Each gameweek the lab saves its final pre-deadline recommendation (the Plan tab's transfers, XI, bench, captain), freezes it at the deadline and scores it once FPL finishes the gameweek: the recommended 15 with FPL autosub and captain rules, minus its hits, against ${they?"their":"your"} real points net of hits.</p>${rows.map(r=>labDecRow(r,they)).join("")}`;
}
// ---------------------------------------------------------------- shell
function labShell(D,opt){
  opt=opt||{}; const they=!!opt.they;
  const KEY="fpl-lab:view:"+(opt.key||"x");
  document.body.classList.add("lab"); document.documentElement.classList.add("lab-html");
  const root=document.createElement("div"); root.id="lab";
  const tabs=[["plan","Plan",LAB_SVG.plan],["target","Target",LAB_SVG.target],["more","More",LAB_SVG.more]];
  const C=labCaptainPanel(D,they), Tr=labTransfer(D);
  const gw=(D.deadline||{}).next_gw;
  root.innerHTML=`<header class="lab-head"><div class="lab-brand"><span>FPL Lab</span>${LAB_SVG.flask}</div><div class="lab-team">${esc((D.team||{}).name||opt.team||"")}</div><button class="lab-ibtn" aria-label="About this page" aria-expanded="false">${LAB_SVG.info}</button></header>
<div class="lab-info" hidden></div>
<main class="lab-main">
<div class="lab-view" id="labPlan"><div class="lab-top"></div>
<div class="lab-do card"><h2>DO THIS${gw?` <span class="note">· GW${gw}</span>`:""}</h2><div class="lab-tiles">
<button class="lab-tile cap" data-p="labCap" aria-expanded="false"><span class="lab-ic">${LAB_SVG.shield}</span><span class="lab-tx"><b class="lab-tt">CAPTAIN</b><em>C <strong>${esc(C.cap)}</strong><br>VC ${esc(C.vc)}</em></span></button>
<button class="lab-tile tr" data-p="labTr" aria-expanded="false"><span class="lab-ic">${LAB_SVG.swap}</span><span class="lab-tx"><b class="lab-tt">TRANSFER</b><em>Make up to ${esc(String(Tr.ft))} free transfer${Tr.ft===1?"":"s"}:<br>${Tr.names}</em></span></button></div>
<div class="lab-panel" id="labCap" hidden>${C.html}</div><div class="lab-panel" id="labTr" hidden>${((D.plan||{}).transfer||{}).reason?`<p class="note">${esc(D.plan.transfer.reason)}</p>`:""}${typeof plannerCardCompact==="function"?plannerCardCompact(D):""}</div>${labDecLast(D,they)}</div>
${labPitch(D,they,KEY)}
${labAcc("labChips","CHIPS","View chip status and strategy",labChips(D,they))}
${labAcc("labLeague","LEAGUE","Current standings and rivals",labLeague(D,they))}
${labAcc("labNews","FPL NEWS","Injuries, suspensions &amp; key updates",labNews(D,they))}
</div>
<div class="lab-view" id="labTarget"></div>
<div class="lab-view" id="labMore"></div>
<div class="lab-foot"><i>All times are in ET (Toronto)</i><div>${LAB_SVG.refresh} Last updated: ${labWhen(D.generated_at)}</div></div>
</main>
<nav class="lab-bottom">${tabs.map(([id,l,ic])=>`<button data-v="${id}">${ic}<span>${l.toUpperCase()}</span></button>`).join("")}</nav>`;
  document.body.insertBefore(root,document.body.firstChild);
  // PLAN: live/deadline/chip banners stay at the top
  const top=root.querySelector(".lab-top");
  ["deadlineBanner","liveBar","chipAlert"].forEach(id=>{const e=document.getElementById(id); if(e) top.appendChild(e);});
  // info panel: the old header line, KPIs and links
  const info=root.querySelector(".lab-info");
  ["meta","kpis"].forEach(id=>{const e=document.getElementById(id); if(e) info.appendChild(e);});
  const foot=document.getElementById("foot"); if(foot) info.appendChild(foot);
  info.insertAdjacentHTML("afterbegin",`<p class="note">FPL Lab for ${esc((D.team||{}).name||"")}: Plan = what to do before the next deadline, Target = players worth buying, More = every other tool (review, AI team, strategy, intel, leagues). Data refreshes automatically from FPL's public API.</p>`);
  // TARGET
  labTargetView(D,root.querySelector("#labTarget"),they);
  // MORE: every old section, grouped like the old tabs
  const more=root.querySelector("#labMore");
  const groups=(typeof TAB_GROUPS!=="undefined"?TAB_GROUPS:[]);
  more.innerHTML=`<div class="lab-menu" id="labMenu"></div><div id="labPages"></div>`;
  const menu=more.querySelector("#labMenu"), pages=more.querySelector("#labPages");
  // every More entry is a button that opens its own page (no dropdowns); `subs` = [[label, element]] become pill tabs inside the page
  const addPage=(id,title,sub,build)=>{
    const btn=document.createElement("button"); btn.type="button"; btn.className="lab-mi"; btn.dataset.page=id;
    btn.innerHTML=`<span><b>${esc(title)}</b><em>${sub}</em></span><i>${LAB_SVG.chev}</i>`; menu.appendChild(btn);
    const pg=document.createElement("div"); pg.className="lab-mpage"; pg.id=id; pg.hidden=true;
    pg.innerHTML=`<div class="lab-mhead"><button type="button" class="lab-back" data-back="1">&#8592; More</button><h2>${esc(title)}</h2></div><div class="lab-mbody"></div>`;
    build(pg.querySelector(".lab-mbody")); pages.appendChild(pg);
  };
  addPage("more-pred","Predictions",`Goals, assists, clean sheets &amp; rotation for GW${esc(String((D.predictions||{}).gw||""))}`,body=>{ body.innerHTML=labPred(D); });
  if(D.decision_log) addPage("more-declog","Decision log",`${they?"Their":"Your"} moves vs the model's, scored each GW`,body=>{ body.innerHTML=labDecLog(D,they); });
  groups.forEach(g=>{
    addPage("more-"+g.id,g.label,esc(g.tabs.map(t=>t[1]).join(" · ")),body=>{
      const subs=g.tabs.map(([id,label])=>[label,document.getElementById(id)]).filter(x=>x[1]);
      if(subs.length===1){ body.appendChild(subs[0][1]); return; }
      const bar=document.createElement("div"); bar.className="lab-stabs";
      const panes=subs.map(([label,s],i)=>{ const pane=document.createElement("div"); pane.className="lab-spane"; pane.hidden=i>0; pane.appendChild(s);
        const bt=document.createElement("button"); bt.type="button"; bt.textContent=label; bt.dataset.sub=String(i); if(i===0) bt.className="on"; bar.appendChild(bt); return pane; });
      bar.addEventListener("click",e=>{ const bt=e.target.closest("button[data-sub]"); if(!bt) return; e.stopPropagation();
        bar.querySelectorAll("button").forEach(x=>x.classList.toggle("on",x===bt)); panes.forEach((p,i)=>{p.hidden=String(i)!==bt.dataset.sub;}); });
      body.appendChild(bar); panes.forEach(p=>body.appendChild(p));
    });
  });
  // any section not in a group (future additions) still shows
  document.querySelectorAll("body > section").forEach(s=>{ if(!s.innerHTML.trim()) return; addPage("more-"+s.id,s.id.toUpperCase(),"",body=>body.appendChild(s)); });
  const openPage=id=>{ const pg=document.getElementById(id); if(!pg) return; menu.hidden=true; pages.querySelectorAll(".lab-mpage").forEach(x=>x.hidden=x!==pg); window.scrollTo(0,0); };
  const closePage=()=>{ pages.querySelectorAll(".lab-mpage").forEach(x=>x.hidden=true); menu.hidden=false; window.scrollTo(0,0); };
  // view switching (top tabs and bottom nav)
  const show=v=>{ if(!["plan","target","more"].includes(v)) v="plan";
    root.querySelectorAll(".lab-view").forEach(x=>x.classList.toggle("on",x.id==="lab"+v[0].toUpperCase()+v.slice(1)));
    root.querySelectorAll("[data-v]").forEach(b=>{b.classList.toggle("on",b.dataset.v===v); b.setAttribute("aria-current",b.dataset.v===v?"page":"false");});
    try{localStorage.setItem(KEY,v);}catch(e){} };
  root.addEventListener("click",e=>{
    const b=e.target.closest("button"); if(!b||!root.contains(b)) return;
    if(b.dataset.page){ openPage(b.dataset.page); }
    else if(b.dataset.back){ closePage(); }
    else if(b.dataset.v){ if(b.dataset.v==="more"&&more.classList.contains("on")) closePage(); show(b.dataset.v); window.scrollTo(0,0); }
    else if(b.dataset.p){ const p=root.querySelector("#"+b.dataset.p); const open=p.hidden; root.querySelectorAll(".lab-panel").forEach(x=>x.hidden=true); root.querySelectorAll(".lab-tile").forEach(x=>x.setAttribute("aria-expanded","false")); p.hidden=!open; b.setAttribute("aria-expanded",String(open)); }
    else if(b.dataset.declog){ show("more"); openPage("more-declog"); const r=document.getElementById("declog-"+b.dataset.declog); if(r){ r.open=true; setTimeout(()=>r.scrollIntoView({block:"start"}),30);} }
    else if(b.classList.contains("lab-ibtn")){ info.hidden=!info.hidden; b.setAttribute("aria-expanded",String(!info.hidden)); }
  });
  let v="plan"; try{v=localStorage.getItem(KEY)||"plan";}catch(e){}
  show(v);
}
