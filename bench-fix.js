(function(){
  const D=window.FPL_DATA; if(!D) return;
  const b=D.bench_audit;
  if(b){
    if(b.gw2){ b.gw2.process=114; b.gw2.hindsight=128; }
    if(b.gw3){ b.gw3.process=51; b.gw3.hindsight=58; }
  }
  const fh=(D.chips_official||{}).freehit;
  if(fh==null||!D.transfers) return;
  D.transfers=D.transfers.filter(t=>t.gw!==fh);
})();
