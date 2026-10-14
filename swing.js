/* Fixture swing card. Needs esc() from dashboard-common.js (falls back to a local one).
   Usage: el.innerHTML=fixtureSwingCard(D); initFixtureSwing(el,D); */
(function(){
  const E=(typeof esc==="function")?esc:s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const KINDS=[["fdr","Overall"],["att","Attack"],["def","Defence"]];
  const BG={1:"rgba(61,220,151,.45)",2:"rgba(61,220,151,.22)",3:"rgba(230,195,92,.25)",4:"rgba(232,93,76,.30)",5:"rgba(232,93,76,.55)"};
  const mean=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;
  const f1=v=>v==null?"-":v.toFixed(1);
  const num=v=>(typeof v==="number"&&isFinite(v))?v:null;
  const val=(f,k)=>{const v=num(f[k]);return v!=null?v:num(f.fdr);};

  function windows(S){const n=(S.gws||[]).length;return [3,6,8].filter(w=>w<=n).concat(n&&n<3?[n]:[]).filter((w,i,a)=>a.indexOf(w)===i);}

  function compute(S,W,kind){
    const near=Math.max(1,Math.min(S.near||2,W-1||1));
    return (S.clubs||[]).map(c=>{
      const cells=(c.cells||[]).slice(0,W);
      const per=cells.map(x=>mean((x.fixtures||[]).map(f=>val(f,kind)).filter(v=>v!=null)));
      const all=[];cells.forEach(x=>(x.fixtures||[]).forEach(f=>{const v=val(f,kind);if(v!=null)all.push(v);}));
      const nearV=[],laterV=[];
      cells.forEach((x,i)=>(x.fixtures||[]).forEach(f=>{const v=val(f,kind);if(v==null)return;(i<near?nearV:laterV).push(v);}));
      const run=mean(all),a=mean(nearV),b=mean(laterV);
      return {c,cells,run,swing:(a!=null&&b!=null)?a-b:null,dgw:cells.some(x=>x.double||(x.fixtures||[]).length>1),own:c.own||0};
    });
  }

  function swingLabel(s){
    if(s==null)return '<span style="color:var(--muted)">-</span>';
    if(s>=0.5)return `<span class="pos">easier later</span>`;
    if(s<=-0.5)return `<span class="neg">harder later</span>`;
    return '<span style="color:var(--muted)">steady</span>';
  }
  const ownPill=r=>r.own?`<span class="pill free" title="${E((r.c.players||[]).join(", "))}">you own ${r.own}</span>`:"";
  const OWNBG="box-shadow:inset 3px 0 0 var(--teal);background:rgba(27,127,110,.14)";

  function row(r,kind){
    const risk=r.own&&r.swing!=null&&r.swing<=-0.75?` <span class="pill used">swing risk</span>`:"";
    const dgw=r.dgw?` <span class="pill mid">DGW</span>`:"";
    const pl=r.own&&(r.c.players||[]).length?`<div style="font-size:10px;color:var(--muted)">${E((r.c.players||[]).join(", "))}</div>`:"";
    return `<li style="${r.own?OWNBG+";padding-left:8px":""}"><span class="who">${E(r.c.club)} <span style="color:var(--muted);font-weight:400">${f1(r.run)}</span>${dgw}${ownPill(r)}${risk}</span><span style="font-size:12px">${swingLabel(r.swing)}</span>${pl?`<span class="detail" style="margin-top:0">${pl.replace(/^<div[^>]*>|<\/div>$/g,"")}</span>`:""}</li>`;
  }

  function cell(x,kind){
    if(!x)return `<td></td>`;
    const fx=x.fixtures||[];
    if(x.blank||!fx.length)return `<td title="Blank gameweek" style="background:repeating-linear-gradient(45deg,transparent 0 3px,rgba(139,149,161,.25) 3px 6px);color:var(--muted);font-weight:700;text-align:center">BLANK</td>`;
    const rows=fx.map(f=>{
      const v=val(f,kind),b=BG[Math.max(1,Math.min(5,Math.round(v==null?3:v)))];
      const t=`${f.opp} (${f.side}) ${kind}: ${v==null?"n/a":v}`+(f.elo_diff!=null?` | Elo gap ${f.elo_diff>0?"+":""}${Math.round(f.elo_diff)}`:"");
      return `<div title="${E(t)}" style="background:${b};border-radius:3px;margin:1px 0;text-align:center">${E(f.opp)} <span style="opacity:.75">(${E(f.side)})</span></div>`;
    }).join("");
    return `<td style="padding:2px 1px">${rows}</td>`;
  }

  window.fixtureSwingCard=function(D,opts){
    const S=D&&D.swing;
    if(!S||!(S.clubs||[]).length||!(S.gws||[]).length)return "";
    opts=opts||{};
    const ws=windows(S),maxW=ws[ws.length-1];
    let W=parseInt(opts.w,10);if(!(ws.indexOf(W)>=0))W=ws.indexOf(6)>=0?6:maxW;
    const kind=KINDS.some(k=>k[0]===opts.k)?opts.k:"fdr";
    const rows=compute(S,W,kind).filter(r=>r.run!=null);
    const sorted=rows.slice().sort((a,b)=>a.run-b.run);
    const easy=sorted.slice(0,5),hard=sorted.slice().reverse().slice(0,5).filter(r=>!easy.includes(r));
    const ownRisk=rows.filter(r=>r.own&&r.swing!=null&&r.swing<=-0.75&&!hard.includes(r)&&!easy.includes(r));
    const btn=(attr,v,label,on)=>`<button type="button" data-${attr}="${E(v)}" aria-pressed="${on}" style="font:inherit;font-size:12px;padding:5px 11px;margin:0 4px 4px 0;border-radius:999px;cursor:pointer;border:1px solid ${on?"var(--teal)":"var(--line)"};background:${on?"var(--teal)":"transparent"};color:${on?"#fff":"var(--ink)"}">${E(label)}</button>`;
    const ctr=`<div>${ws.map(w=>btn("w",w,w+" GWs",w===W)).join("")}</div><div>${KINDS.map(k=>btn("k",k[0],k[1],k[0]===kind)).join("")}</div>`;
    const gws=(S.gws||[]).slice(0,W);
    const head=`<tr><th style="width:40px;text-align:left">Club</th>${gws.map(g=>`<th>GW${E(g)}</th>`).join("")}<th style="width:30px">Run</th><th style="width:60px;text-overflow:clip">Swing</th></tr>`;
    const body=sorted.map(r=>`<tr style="${r.own?OWNBG:""}"><td style="text-align:left;font-weight:700"${r.own?` title="${E("You own: "+(r.c.players||[]).join(", "))}"`:""}>${E(r.c.club)}${r.own?` <span style="color:var(--teal)">&bull;${r.own}</span>`:""}</td>${gws.map((g,i)=>cell(r.cells[i],kind)).join("")}<td><b>${f1(r.run)}</b></td><td class="wrap" style="font-size:9px;line-height:1.15">${swingLabel(r.swing)}</td></tr>`).join("");
    const wc=D.chips_official||{},nx=D.deadline&&D.deadline.next_gw;
    const wcUsed=(nx!=null&&nx>=20)?wc.wildcard_h2:wc.wildcard;
    const chip=(S.show_chip_hint&&wcUsed==null&&(D.chips_official||{}).hasOwnProperty("wildcard"))?`<p class="note" style="margin:8px 0 0">Wildcard available: a swing like this is the kind of run to plan one around.</p>`:"";
    const list=(t,a,extra)=>`<h3>${t}</h3><ul class="chiplist">${a.map(r=>row(r,kind)).join("")}${(extra||[]).map(r=>row(r,kind)).join("")}</ul>`;
    return `<div class="card" data-fswing="1"><h2>Fixture swing</h2>${ctr}
${list("Clubs to target",easy)}${list("Clubs to sell / avoid",hard,ownRisk)}
<h3>All clubs, next ${W} GWs (${E((KINDS.find(k=>k[0]===kind)||[])[1])})</h3>
<div class="table-scroll"><table class="table-compact" style="min-width:${Math.max(330,70+W*44)}px">${head}${body}</table></div>
<p class="note" style="margin-top:8px">Difficulty is FPL's own rating; Attack/Defence use the opponent's defensive/attacking strength. Clubs you own are highlighted. Swing = fixtures now minus later: "easier later" means hard now, easy later.</p>${chip}</div>`;
  };

  window.initFixtureSwing=function(root,D){
    if(!root)return;
    if(root._fsBound){root._fsD=D;return;}
    root._fsBound=true;root._fsD=D;
    root.addEventListener("click",ev=>{
      const b=ev.target.closest&&ev.target.closest("button[data-w],button[data-k]");
      if(!b||!root.contains(b))return;
      if(b.dataset.w)root.dataset.w=b.dataset.w;
      if(b.dataset.k)root.dataset.k=b.dataset.k;
      root.innerHTML=window.fixtureSwingCard(root._fsD,{w:root.dataset.w,k:root.dataset.k});
    });
  };
})();
