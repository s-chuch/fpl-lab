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
  const blob=pool.map(x=>String(x.text||"").toLowerCase()).join(" | ");
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
  const ownedHits=[];
  for(const n of ["De Cuyper","João Pedro","Szoboszlai","Haaland","Groß","Groß"]) if(have.has(n)||have.has("Groß")||have.has("Gross")) ownedHits.push(n);
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
  if(gwB){
    chipRows.push(chipState("wildcard","Wildcard",gwB,"CONSIDER",
      wantsWC?"This is the window News actually wants: after GW"+gwA+" and the international break, once minutes settle.":"Revisit after the break. Not automatic."));
  }
  const mustMove=[];
  if(fadeUnited && (have.has("B.Fernandes")||have.has("Shaw"))) mustMove.push("News/X fade United. Shaw is already a sit. Fernandes vs Fulham is still startable — do not fire him this week just to match the fade.");
  const blocked=targets.filter(n=>!have.has(n));
  let action="ROLL", moveLine="Roll. Keep both free transfers.", reason="";
  if(blocked.length && bank<1){
    reason="News/X want "+blocked.join(", ")+". Bank is £"+bank.toFixed(1)+"m. Those names do not fit without selling a core mid/fwd. Fielding 11 is fine, so rolling is the process play.";
  } else if(!blocked.length){
    reason="You already own the agreed core (Haaland, João Pedro, De Cuyper, Szoboszlai). Nothing required.";
  } else {
    reason="Targets are "+blocked.join(", ")+". Only move if the sell is already a sit for both upcoming GWs.";
  }
  const optional=[];
  if(have.has("Cherki") && blocked.includes("Rogers")) optional.push("Only if you refuse to roll: Cherki → Rogers. Prices line up. Cherki vs Sunderland at home is a reason not to.");
  if(have.has("Calvert-Lewin") && blocked.includes("Wissa")) optional.push("DCL → Wissa is the cheap forward version of the same idea. DCL vs Palace at home is startable this week.");
  if(have.has("Tzolis") && blocked.includes("Gakpo")) optional.push("Tzolis → Gakpo needs another £0.5m you do not have. Sit Tzolis instead.");
  return {chipRows, action, moveLine, reason, optional, mustMove, targets:blocked, wantsWC, ft, bank, gwA, gwB};
};
