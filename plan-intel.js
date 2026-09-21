window.planIntel = function(D){
  const N0=window.FPL_NEWS||{}, X0=window.FPL_X||{};
  const P=D.plan||{}, up=P.upcoming||[];
  const deadline=D.deadline||{};
  const intelGw=P.intel_gw||deadline.intel_gw||deadline.next_gw||(up.find(u=>!u.deadline_passed)||up[0]||{}).gw;
  const lockedGw=P.locked_gw||deadline.locked_gw;
  function fresh(obj){
    if(!obj||intelGw==null) return obj||{};
    if(obj.gw==null) return {};
    return Number(obj.gw) >= Number(intelGw) ? obj : {};
  }
  const N=fresh(N0), X=fresh(X0);
  const scrapeGws=[N0.gw, X0.gw].filter(g=>g!=null).map(Number);
  const bestScrape=scrapeGws.length?Math.max.apply(null, scrapeGws):0;
  const themePool=[].concat(N.agreed||[], N.split||[], X.agreed||[], X.split||[]);
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
      reason:P.intel_note||("GW"+(lockedGw||"?")+" is locked. News/X themes for the locked GW are not current Plan advice."),
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
  const chips=D.chips_official||{};
  const bank=Number((D.team||{}).bank||0);
  const ft=(P.transfer||{}).ft_available;
  const pool=[].concat(N.agreed||[], X.agreed||[], X.split||[], N.split||[]);
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
  for(const it of [].concat(N.agreed||[], X.agreed||[])){
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
      wantsWC?"News/X flag a wildcard window, but there is no case yet this week.":"No wildcard consensus for this week."));
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
  const haalandOwn=(Tac.template||[]).find(x=>x.name==="Haaland");
  const haalandFdr=((((P.rows||[]).find(r=>r[1]==="Haaland")||[])[4]));
  let cap="Captain Haaland. He is the league default.";
  if(haalandFdr!=null && Number(haalandFdr)>=4 && wc.length){
    cap="Haaland FDR "+haalandFdr+". Cap-diff only if the alt is owned by 3 or fewer here: "+wc.join(", ")+".";
  } else if(wantsHaalandCap){
    cap="Captain Haaland. News/X and this league both default to him.";
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

  // Defend mode: once you're top of this mini-league, the room's own template
  // and news/X consensus matter less than the two teams actually chasing you.
  // Tac.first/Tac.second are already "closest rivals by rank" (see
  // league_tactics.py) — when you're rank 1 that's literally P2/P3.
  const isDefend=Tac.you_rank===1 || (Tac.gap_to_first!=null && Tac.gap_to_first<=0);
  function describeRival(card){
    if(!card) return null;
    const gap=card.gap;
    const gapTxt=gap==null?"":(gap<0?(" · "+Math.abs(gap)+" back"):(gap>0?(" · "+gap+" ahead"):" · level"));
    const chipsTxt=(card.chips_used&&card.chips_used.length)?(" · used "+card.chips_used.join(", ")):"";
    return (card.name||"?")+" · "+(card.pts??"?")+" pts"+gapTxt+chipsTxt;
  }
  const threat=isDefend?[describeRival(Tac.first),describeRival(Tac.second)].filter(Boolean):[];
  const defendTransfer=(cheapHit && bank>=1 && sitSells.length)
    ?("Consider "+sitSells[0]+" → "+cheapHit+". Funds a name this room barely owns while you defend the lead.")
    :"Roll. Keep transfers banked while you defend the lead.";

  const pairs=[
    {sell:"Cherki", buy:"Rogers", needBank:0, note:"Prices line up on Cherki → Rogers."},
    {sell:"Calvert-Lewin", buy:"Wissa", needBank:0, note:"DCL → Wissa is the cheap forward version."},
    {sell:"Tzolis", buy:"Gakpo", needBank:0.5, note:"Tzolis → Gakpo needs a little bank."},
  ];

  let action="ROLL", moveLine="Roll. Keep both free transfers.", reason="";
  let chosen=null;
  for(const p of pairs){
    if(!have.has(p.sell) || !blocked.includes(p.buy)) continue;
    if(bank + 1e-9 < p.needBank) continue;
    const strongSit=doubleSit(p.sell);
    const strongHit=!!cheapHit && cheapHit===p.buy && bank>=1;
    if(strongSit || strongHit){ chosen=p; break; }
  }
  if(!chosen && cheapHit && bank>=1 && sitSells.length){
    chosen={sell:sitSells[0], buy:cheapHit, needBank:0, note:"Scarce agreed name vs a double-sit sell."};
  }

  if(chosen){
    action="CONSIDER";
    moveLine="Consider "+chosen.sell+" → "+chosen.buy+".";
    reason=(chosen.note?chosen.note+" ":"")+"Agreed missing target with "+(doubleSit(chosen.sell)?"a double-sit/doubt sell":"bank/hit cover")+". Only pull the trigger if you still like the buy after team news.";
  } else if(cheapHit && bank>=1){
    reason="A News/X name this room barely owns could fit. Still only move if the sell is a sit both weeks.";
  } else if(blocked.length && bank<1){
    reason="News/X want "+blocked.join(", ")+". Bank is £"+bank.toFixed(1)+"m. Those names wait for the Wildcard. Rolling is the process play.";
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
  if(fadeUnited && (have.has("B.Fernandes")||have.has("Shaw"))) optional.push("News/X fade United. Shaw is already a sit. Do not fire Fernandes this week to match a fade.");
  const they=(Tac.they_share||[]).map(x=>x.name);
  if(they.length) optional.push("Do not buy "+they.join(", ")+" this week. 1st and 2nd already own them — that is insurance, not a differential.");
  return {
    cleared:false,
    waiting:false,
    intelGw, lockedGw,
    chipRows, action, moveLine, reason, optional, targets:blocked, wantsWC, ft, bank, gwA, gwB,
    league: {
      league: esl.name||"",
      mode: isDefend?"defend":"chase",
      cap, transfer: isDefend?defendTransfer:reason,
      start, bench, wc, threat,
      gap: Tac.gap_to_first,
      first: Tac.first&&Tac.first.name,
      second: Tac.second&&Tac.second.name
    }
  };
};
