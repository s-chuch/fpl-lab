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
function agreedPool(){const N=window.FPL_NEWS||{},X=window.FPL_X||{}; return [].concat((N.agreed||[]).map(x=>({text:x.text,from:"News",player:x.player,club:x.club,tags:x.tags,sources:x.sources})),(X.agreed||[]).map(x=>({text:x.text,from:"X",player:x.player,club:x.club,tags:x.tags,sources:x.sources})));}
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
  const TAG_LABEL={called_it:"Called it","captain talk":"Captain","transfer target":"Transfer",chip:"Chip","rotation risk":"Rotation"};
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
  const range=(G.earliest&&G.latest)?`${esc(toToronto(G.earliest))} → ${esc(toToronto(G.latest))}`:"—";
  const cg=G.call_grades||{};
  const record=cg.graded?`<div class="card"><h2>Captain/transfer call record</h2><p class="note">${cg.good_pct}% good · ${cg.mixed_pct}% mixed · ${cg.bad_pct}% bad — ${cg.graded} graded call${cg.graded===1?"":"s"}${cg.pending?`, ${cg.pending} pending (GW not played yet)`:""}.</p><ul class="note-list"><li>Auto-graded from actual points</li><li>Captain call: "good" at 8+ points, "bad" at 2 or fewer</li><li>Transfer target: "good" at 6+, "bad" at 1 or fewer — everything between is "mixed"</li><li>A blunt heuristic on whichever single GW the call was for, not a judgment of the reasoning</li></ul></div>`:"";
  document.getElementById("greekgod").innerHTML=`<div class="card"><h2>@${esc(G.handle||"greekgodFpl")}</h2><p class="note">${G.post_count??0} posts archived · ${range}</p><ul class="note-list"><li>Live X ingest only started partway through this season — coverage begins from when tracking started, not GW1</li><li>"Called it" flags self-referential prediction language for you to judge against what happened — that part still isn't automated</li></ul></div>${record}<div class="card"><h2>Most-mentioned players</h2><div class="xi">${mentions}</div></div><div class="card"><h2>Most-mentioned clubs</h2><div class="xi">${clubs}</div></div><div class="card"><h2>Captain / transfer / chip calls</h2><ul class="chiplist">${calls}</ul></div>`;
}
// Freshness line + stale-data banner for the News/X tabs (shared by both pages).
function freshnessMeta(obj, kind){
  const gen=obj.generated_at?esc(toToronto(obj.generated_at)):esc(obj.generated_at_et||"—");
  const cut=obj.cutoff?esc(toToronto(obj.cutoff)):"—";
  const bits=[`Scraped ${gen}`, `cutoff ${cut}`];
  if(obj.mode) bits.push("mode "+esc(obj.mode));
  return `<p class="note">${bits.join(" · ")}</p>`;
}
function staleWarn(obj, kind){
  const gw=obj.gw!=null?("GW"+obj.gw):"this GW";
  if(kind==="news" && (obj.no_new || !(obj.new_articles||[]).length))
    return `<div class="warn">No new articles this run for ${gw}. Themes may be stale — check generated time.</div>`;
  if(kind==="x"){
    if((obj.mode||"manual")==="live"){
      if(obj.no_new || !(obj.new_posts||[]).length)
        return `<div class="warn">No new X posts this run for ${gw}. Themes may be stale — check generated time.</div>`;
      return "";
    }
    return `<div class="warn">X themes are manual/seeded until live ingest exists. Not a live scrape.</div>`;
  }
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
