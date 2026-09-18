(function(){
  const D=window.FPL_DATA; if(!D) return;
  // bench_audit.process is now computed server-side in refresh.py (minutes-based,
  // not a copy of "you") — no client-side patch needed here any more.
  const fh=(D.chips_official||{}).freehit;
  if(fh==null||!D.transfers) return;
  function netOf(t){const n=Number(String(t&&t.net!=null?t.net:0).replace("+",""));return Number.isFinite(n)?n:0;}
  function collapse(rows){
    const keep=rows.slice();
    let changed=true;
    while(changed){
      changed=false;
      outer: for(let i=0;i<keep.length;i++){
        for(let j=i+1;j<keep.length;j++){
          if(keep[i].out===keep[j].inn && keep[i].inn===keep[j].out){
            keep.splice(j,1);
            keep.splice(i,1);
            changed=true;
            break outer;
          }
        }
      }
    }
    return keep.filter(t=>netOf(t)!==0).map(t=>Object.assign({},t,{verdict:(t.verdict||"")+" · FH net"}));
  }
  const perm=D.transfers.filter(t=>t.gw!==fh);
  const cleaned=collapse(D.transfers.filter(t=>t.gw===fh));
  D.transfers=perm.concat(cleaned);
})();
