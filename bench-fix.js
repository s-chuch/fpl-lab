(function(){
  const D=window.FPL_DATA; if(!D) return;
  const b=D.bench_audit;
  if(b){
    if(b.gw2){ b.gw2.process=114; b.gw2.hindsight=128; }
    if(b.gw3){ b.gw3.process=51; b.gw3.hindsight=58; }
  }
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
