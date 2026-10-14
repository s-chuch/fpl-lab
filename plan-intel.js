window.planIntel = function(D){
  const N0=window.FPL_NEWS||{};
  const P=D.plan||{}, up=P.upcoming||[];
  const deadline=D.deadline||{};
  const intelGw=P.intel_gw||deadline.intel_gw||deadline.next_gw||(up.find(u=>!u.deadline_passed)||up[0]||{}).gw;
  const lockedGw=P.locked_gw||deadline.locked_gw;
  function fresh(obj){
    if(!obj||intelGw==null) return obj||{};
    if(obj.gw==null) return {};
    return Number(obj.gw) >= Number(intelGw) ? obj : {};
  }
  const N=fresh(N0);
  const scrapeGws=[N0.gw].filter(g=>g!=null).map(Number);
  const bestScrape=scrapeGws.length?Math.max.apply(null, scrapeGws):0;
  const themePool=[].concat(N.agreed||[], N.split||[]);
  const hasFreshThemes=themePool.length>0;
  const namesLocked=lockedGw!=null && themePool.some(it=>new RegExp("GW"+lockedGw+"\\b","i").test(String(it.text||"")));
  // After GW N locks, intel_gw becomes N+1. Clear until scrapes are labeled for that GW
  // with themes that do not still name the locked GW.
  const clear=!!(intelGw!=null && (bestScrape < Number(intelGw) || !hasFreshThemes || namesLocked));
  if(clear){
    const wait=intelGw||((lockedGw||0)+1);
    return {
      cleared:true,
      waiting:true,
      intelGw:wait,
      lockedGw:lockedGw,
      chipRows:[],
      action:"WAIT",
      moveLine:"Waiting for GW"+wait+" intel.",
      reason:P.intel_note||("GW"+(lockedGw||"?")+" is locked. News themes for the locked GW are not current Plan advice."),
      optional:[],
      targets:[],
      wantsWC:false,
      ft:(P.transfer||{}).ft_available,
      bank:Number((D.team||{}).bank||0),
      gwA:wait,
      gwB:null,
      league:{league:"",cap:"",transfer:"",start:[],bench:[],wc:[]}
    };
  }
  const squad=(P.rows||[]).map(r=>r[1]);
  const clubs={}; (P.rows||[]).forEach(r=>clubs[r[1]]=r[2]);
  const have=new Set(squad);
  // A transfer swaps like for like: a keeper for a keeper, a midfielder for a midfielder. Positions come from
  // the squad rows and the all-player name -> position map the refresh writes (unknown = not suggested).
  const POSMAP=D.pos_by_name||{};
  const posOf=n=>{const r=(P.rows||[]).find(x=>x[1]===n); return (r&&r[0])||POSMAP[n]||null;};
  const samePos=(a,b)=>{const pa=posOf(a), pb=posOf(b); return !!pa && pa===pb;};
  const chips=D.chips_official||{};
  const bank=Number((D.team||{}).bank||0);
  const ft=(P.transfer||{}).ft_available;
  const pool=[].concat(N.agreed||[], N.split||[]);
  const blob=pool.map(x=>String(x.text||"")).join(" | ").toLowerCase();
  const wantsWC=/wildcard/.test(blob);
  const wantsFH=/free hit/.test(blob);
  // Prefer the structured player/tags news_scrape.py's discovery emits; fall back
  // to loose blob text for X items (curated/live-ingested free text, no player field).
  const wantsHaalandCap=pool.some(it=>it.player==="Haaland" && (it.tags||[]).includes("captain talk")) || (/haaland/.test(blob) && /captain/.test(blob));
  const fadeUnited=pool.some(it=>it.club==="MUN" && (it.tags||[]).includes("fade/sell")) || /united assets are a fade/.test(blob);
  const targets=[];
  // Legacy free-text fallback for X items, which are curated/live-ingested and
  // don't carry a structured player field the way news_scrape.py's discovered
  // themes do.
  const names=[["gakpo","Gakpo"],["isak","Isak"],["rogers","Rogers"],["gibbs-white","Gibbs-White"],["gibbs white","Gibbs-White"],["gvardiol","Gvardiol"],["saka","Saka"],["wissa","Wissa"],["palmer","Palmer"]];
  for(const it of (N.agreed||[])){
    if(it.player){
      if(!have.has(it.player) && !targets.includes(it.player)) targets.push(it.player);
      continue;
    }
    const t=String(it.text||"").toLowerCase();
    if(!/target|transfer in|priority|popular|attacker to target/.test(t)) continue;
    for(const [k,n] of names){ if(t.includes(k) && !have.has(n) && !targets.includes(n)) targets.push(n); }
  }
  function chipState(key, label, gw, rec, why){
    const used=chips[key]!=null;
    return {key,label,gw,used,rec: used?"USED":rec, why: used?("Already played GW"+chips[key]+"."):why};
  }
  const openUp=up.filter(u=>!u.deadline_passed);
  const gwA=(openUp[0]&&openUp[0].gw)||intelGw||(up[0]&&up[0].gw);
  const gwB=(openUp[1]&&openUp[1].gw)||(up[1]&&!up[1].deadline_passed&&up[1].gw)||(up[1]&&up[1].gw);
  // Bench Boost reads the actual bench for the open GW off the existing call
  // column (P.rows), rather than naming specific players/fixtures that go
  // stale the moment the gameweek changes.
  const idxA=up.findIndex(u=>u.gw===gwA);
  const benchA=(((P.xis||{})["gw"+gwA]||{}).bench)||[];
  function callAt(name, idx){
    if(idx<0) return null;
    const r=(P.rows||[]).find(row=>row[1]===name);
    return r ? r[5+idx*3] : null;
  }
  const benchAllStart=benchA.length>0 && benchA.every(n=>callAt(n, idxA)==="START");
  const chipRows=[];
  if(gwA){
    chipRows.push(chipState("wildcard","Wildcard",gwA,"HOLD",
      wantsWC?"News flag a wildcard window, but there is no case yet this week.":"No wildcard consensus for this week."));
    chipRows.push(chipState("freehit","Free Hit",gwA,"HOLD",
      wantsFH?"FH drafts are being talked about, but there is no blank/double case to force it.":"No reason to Free Hit a full slate."));
    chipRows.push(chipState("3xc","Triple Captain",gwA,"HOLD",
      wantsHaalandCap?"Haaland is the agreed captain. Armband only.":"No triple-captain case."));
    chipRows.push(chipState("bboost","Bench Boost",gwA,
      benchAllStart?"CONSIDER":"HOLD",
      benchA.length?("Bench is "+benchA.join(", ")+(benchAllStart?" — all read START-quality.":" — not all START-quality.")):"No bench captured for this GW yet."));
  }
  const mini=(D.leagues&&D.leagues.mini)||[];
  const esl=mini.find(x=>x.id===125784)||mini[0]||{};
  const Tac=esl.tactics||{};
  const started=new Set((((((P.xis||{})["gw"+gwA]||{}).xi)||[]).map(n=>String(n).split(" (")[0])));
  const start=[], bench=[];
  for(const u of (Tac.you_unique||[])){
    if(started.has(u.name)) start.push(u.name+" · "+u.count+"/"+u.n);
    else bench.push(u.name+" · sit · "+u.count+"/"+u.n);
  }
  const wc=[];
  const ownByName={};
  for(const u of [].concat(Tac.template||[], Tac.you_unique||[], Tac.they_share||[])) ownByName[u.name]=u.count;
  for(const n of targets){
    const c=ownByName[n];
    if(c==null || c<=3) wc.push(n+(c!=null?" · "+c+"/"+(Tac.n||"?"):" · 0 in room"));
  }
  // The captain is the one the Plan tab, AI team and Wildcard watch share: highest expected points in your XI.
  const xiA=((((P.xis||{})["gw"+gwA]||{}).xi)||[]);
  const capName=(xiA.find(n=>/ \(C\)$/.test(n))||"").replace(/ \(C\)$/,"");
  const capRow=(P.rows||[]).find(r=>r[1]===capName);
  const capFdr=capRow?capRow[4+Math.max(0,idxA)*3]:null;
  const capOwn=(Tac.template||[]).find(x=>x.name===capName);
  let cap=capName?("Captain "+capName+" - highest expected points in your XI"+(capOwn?(", owned by "+capOwn.count+"/"+(Tac.n||"?")+" in this league"):"")+"."):"No captain pick yet.";
  if(capName && capFdr!=null && Number(capFdr)>=4 && wc.length){
    cap="Captain "+capName+" (FDR "+capFdr+"). Cap-diff only if the alt is owned by 3 or fewer here: "+wc.join(", ")+".";
  }
  const blocked=targets.filter(n=>!have.has(n));
  const cheapHit=blocked.find(n=>wc.some(w=>w.indexOf(n)===0));

  function rowOf(name){ return (P.rows||[]).find(r=>r[1]===name); }
  function isSitOrDoubt(s){ return /^(SIT|DOUBT)$/i.test(String(s||"")); }
  function doubleSit(name){
    const r=rowOf(name);
    if(!r) return false;
    return isSitOrDoubt(r[5]) && isSitOrDoubt(r[8]);
  }
  const sitSells=squad.filter(n=>doubleSit(n) && n!=="Haaland");

  // Strategy tier reads off your actual rank in this league, not just
  // "leader or not": rank 1 defends against the two teams chasing you
  // (Tac.first/second are already "closest rivals by rank" — see
  // league_tactics.py — so at rank 1 that's literally P2/P3); rank 2-3 is
  // still realistically chasing the top and uses the same first/second
  // comparison; anything further back shifts the target from 1st/2nd (too
  // far away to be this week's problem) to whoever's directly above you
  // (Tac.neighbors), which is the actual next rival to catch.
  const rank=Tac.you_rank;
  let mode="chase";
  if(rank===1 || (Tac.gap_to_first!=null && Tac.gap_to_first<=0)) mode="defend";
  else if(rank!=null && rank<=3) mode="chase";
  else if(rank!=null) mode="climb";
  function describeRival(card){
    if(!card) return null;
    const gap=card.gap;
    const gapTxt=gap==null?"":(gap<0?(" · "+Math.abs(gap)+" back"):(gap>0?(" · "+gap+" ahead"):" · level"));
    const chipsTxt=(card.chips_used&&card.chips_used.length)?(" · used "+card.chips_used.join(", ")):"";
    return (card.name||"?")+" · "+(card.pts??"?")+" pts"+gapTxt+chipsTxt;
  }
  const nb=Tac.neighbors||null;
  let threat=[];
  if(mode==="defend") threat=[describeRival(Tac.first),describeRival(Tac.second)].filter(Boolean);
  else if(mode==="climb" && nb) threat=[describeRival(nb.above)].filter(Boolean);
  const defendSell=cheapHit?sitSells.find(n=>samePos(n,cheapHit)):null;
  const defendTransfer=(cheapHit && bank>=1 && defendSell)
    ?("Consider "+defendSell+" → "+cheapHit+". Funds a name this room barely owns while you defend the lead.")
    :"Roll. Keep transfers banked while you defend the lead.";

  const pairs=[
    {sell:"Cherki", buy:"Rogers", needBank:0, note:"Prices line up on Cherki → Rogers."},
    {sell:"Calvert-Lewin", buy:"Wissa", needBank:0, note:"DCL → Wissa is the cheap forward version."},
    {sell:"Tzolis", buy:"Gakpo", needBank:0.5, note:"Tzolis → Gakpo needs a little bank."},
  ];

  let action="ROLL", moveLine="Roll. Keep both free transfers.", reason="";
  let chosen=null;
  for(const p of pairs){
    if(!have.has(p.sell) || !blocked.includes(p.buy) || !samePos(p.sell,p.buy)) continue;
    if(bank + 1e-9 < p.needBank) continue;
    const strongSit=doubleSit(p.sell);
    const strongHit=!!cheapHit && cheapHit===p.buy && bank>=1;
    if(strongSit || strongHit){ chosen=p; break; }
  }
  const likeSell=cheapHit?sitSells.find(n=>samePos(n,cheapHit)):null;
  if(!chosen && cheapHit && bank>=1 && likeSell){
    chosen={sell:likeSell, buy:cheapHit, needBank:0, note:"Scarce agreed name vs a double-sit sell."};
  }

  if(chosen){
    action="CONSIDER";
    moveLine="Consider "+chosen.sell+" → "+chosen.buy+".";
    reason=(chosen.note?chosen.note+" ":"")+"Agreed missing target with "+(doubleSit(chosen.sell)?"a double-sit/doubt sell":"bank/hit cover")+". Only pull the trigger if you still like the buy after team news.";
  } else if(cheapHit && bank>=1){
    reason="A News name this room barely owns could fit. Still only move if the sell is a sit both weeks.";
  } else if(blocked.length && bank<1){
    reason="News want "+blocked.join(", ")+". Bank is £"+bank.toFixed(1)+"m. Those names wait for the Wildcard. Rolling is the process play.";
  } else if(!blocked.length){
    reason="You already own the agreed core. Nothing required.";
  } else {
    reason="Targets are "+blocked.join(", ")+". Only move if the sell is already a sit for both upcoming GWs.";
  }

  if(gwB){
    const wcNow=chips.wildcard==null && wc.length>=2;
    chipRows.push(chipState("wildcard","Wildcard",gwB, wcNow?"CONSIDER":"HOLD",
      wcNow?("This room barely owns "+wc.join(", ")+". That is the wildcard case."):"No wildcard case yet. Need two scarce agreed names to force the chip."));
  }
  const optional=[];
  if(have.has("Cherki") && blocked.includes("Rogers")) optional.push("Only if you refuse to roll: Cherki → Rogers. Prices line up.");
  if(have.has("Calvert-Lewin") && blocked.includes("Wissa")) optional.push("DCL → Wissa is the cheap forward version.");
  if(have.has("Tzolis") && blocked.includes("Gakpo")) optional.push("Tzolis → Gakpo needs another £0.5m. Sit Tzolis instead.");
  if(fadeUnited && (have.has("B.Fernandes")||have.has("Shaw"))) optional.push("News fade United. Shaw is already a sit. Do not fire Fernandes this week to match a fade.");
  const they=(Tac.they_share||[]).map(x=>x.name);
  if(they.length) optional.push("Do not buy "+they.join(", ")+" this week. 1st and 2nd already own them — that is insurance, not a differential.");
  // The transfer line is the model plan (planner.py: expected points plus news, ownership, price and rivals), so Plan,
  // AI team and Planner agree. The news-driven idea above stays as an advisory line with its expected-points cost.
  const PL=D.planner||{};
  if((PL.steps||[]).length){
    const mv=(PL.steps[0].moves||[]);
    const follow=PL.recommend==="follow" && mv.length>0;
    const xpBuy=((Object.values(D.news_players||{}).find(p=>chosen && p.name===chosen.buy))||{}).xp;
    const xpSell=(PL.xp0||{})[chosen&&chosen.sell];
    if(chosen && xpBuy!=null && xpSell!=null){
      const d=Math.round((xpBuy-xpSell)*100)/100;
      optional.unshift("News pick: "+chosen.sell+" → "+chosen.buy+" ("+(d>=0?"+":"")+d+" xP this GW) — advisory only, the model plan above decides.");
    }
    action=follow?"CONSIDER":"ROLL";
    moveLine=follow?("Model pick: "+mv.map(m=>m.out+" → "+m.in).join(", ")+"."):"Roll. The model finds no move worth making.";
    reason=follow?("+"+PL.gain+" expected points over rolling across GW"+PL.gws[0]+"-"+PL.gws[PL.gws.length-1]+" ("+PL.gain_extra+" of it from news, price, ownership and rivals). Only pull the trigger if you still like the buy after team news."):("Best plan found is "+(PL.gain>=0?"+":"")+PL.gain+" over rolling. Keep the free transfer.");
  }
  return {
    cleared:false,
    waiting:false,
    intelGw, lockedGw,
    chipRows, action, moveLine, reason, optional, targets:blocked, wantsWC, ft, bank, gwA, gwB,
    league: {
      league: esl.name||"",
      mode,
      cap, transfer: mode==="defend"?defendTransfer:reason,
      start, bench, wc, threat,
      gap: Tac.gap_to_first,
      first: Tac.first&&Tac.first.name,
      second: Tac.second&&Tac.second.name
    }
  };
};
