(function(){
  const D=window.FPL_DATA; if(!D||!D.bench_audit) return;
  const b=D.bench_audit;
  if(b.gw2){ b.gw2.process=114; b.gw2.hindsight=128; }
  if(b.gw3){ b.gw3.process=51; b.gw3.hindsight=58; }
})();
