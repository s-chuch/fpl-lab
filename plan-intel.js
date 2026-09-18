window.planIntel = function(D){
  const N=window.FPL_NEWS||{}, X=window.FPL_X||{};
  const P=D.plan||{}, up=P.upcoming||[];
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
  const wantsHaalandCap=/haaland/.test(blob) && /captain/.test(blob);
  const fadeUnited=/united assets are a fade|fade/.test(blob);
  const targets=[];
  const names=[["gakpo","Gakpo"],["isak","Isak"],["rogers","Rogers"],["gibbs-white","Gibbs-White"],["gibbs white","Gibbs-White"],["gvardiol","Gvardiol"],["saka","Saka"],["wissa","Wissa"],["palmer","Palmer"]];
  for(const it of [].concat(N.agreed||[], X.agreed||[])){
    const t=String(it.text||"").toLowerCase();
    if(!/target|transfer in|priority|popular|attacker to target/.test(t)) continue;
    for(const [k,n] of names){ if(t.includes(k) && !have.has(n) && !targets.includes(n)) targets.push(n); }
  }
  function chipState(key, label, gw, rec, why){
    const used=chips[key]!=null;
    return {key,label,gw,used,rec: used?"USED":rec, why: used?("Already played GW"+chips[key]+"."):why};
  }
  const gwA=up[0]&&up[0].gw, gwB=up[1]&&up[1].gw;
  const chipRows=[];
  if(gwA){
    chipRows.push(chipState("wildcard","Wildcard",gwA,"HOLD",
      wantsWC?"News/X flag a wildcard window, but GW"+gwA+" is the week before the long international break. Wait for GW"+(gwB||gwA+1)+".":"No wildcard consensus for this week."));
    chipRows.push(chipState("freehit","Free Hit",gwA,"HOLD",
      wantsFH?"FH drafts are being talked about. You already spent one. Do not burn another on a full-fixture GW.":"No reason to Free Hit a full slate."));
    chipRows.push(chipState("3xc","Triple Captain",gwA,"HOLD",
      wantsHaalandCap?"Haaland is the agreed captain vs a soft home fixture. Armband only — chip already used.":"No triple-captain case."));
    chipRows.push(chipState("bboost","Bench Boost",gwA,"HOLD","Bench is Shaw (75%) + Hume (City away). Do not boost." ));
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

  // Known affordable/paired moves when News/X agree the buy and we own the sell
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
    // Strong evidence: sell is double-sit/doubt both weeks, OR clearly cheap hit with bank
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
    const wcNow=chips.wildcard==null && wc.length>=2 && wantsWC;
    chipRows.push(chipState("wildcard","Wildcard",gwB, wcNow?"CONSIDER":"HOLD",
      wcNow?("This room barely owns "+wc.join(", ")+". After the break that is the WC case."):"Revisit after the break. Need two scarce agreed names to force the chip."));
  }
  const optional=[];
  if(have.has("Cherki") && blocked.includes("Rogers")) optional.push("Only if you refuse to roll: Cherki → Rogers. Prices line up. Cherki vs Sunderland at home is a reason not to.");
  if(have.has("Calvert-Lewin") && blocked.includes("Wissa")) optional.push("DCL → Wissa is the cheap forward version. DCL vs Palace at home is startable.");
  if(have.has("Tzolis") && blocked.includes("Gakpo")) optional.push("Tzolis → Gakpo needs another £0.5m. Sit Tzolis instead.");
  if(fadeUnited && (have.has("B.Fernandes")||have.has("Shaw"))) optional.push("News/X fade United. Shaw is already a sit. Do not fire Fernandes this week to match a fade.");
  const they=(Tac.they_share||[]).map(x=>x.name);
  if(they.length) optional.push("Do not buy "+they.join(", ")+" this week. 1st and 2nd already own them — that is insurance, not a differential.");
  return {
    chipRows, action, moveLine, reason, optional, targets:blocked, wantsWC, ft, bank, gwA, gwB,
    league: {
      league: esl.name||"",
      cap, transfer: reason,
      start, bench, wc,
      gap: Tac.gap_to_first,
      first: Tac.first&&Tac.first.name,
      second: Tac.second&&Tac.second.name
    }
  };
};
