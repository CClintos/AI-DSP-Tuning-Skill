"""Compare 29 synthetic proposals against release 1.17.0; no hardware claims."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import numpy as np
root=Path(__file__).resolve().parents[1]; scripts=root/'helix-rew-tuner/scripts';sys.path.insert(0,str(scripts))
import pipeline,measure,tunelib
old=types.ModuleType('previous_pipeline');old.__file__=str(scripts/'pipeline.py')
exec(compile(subprocess.check_output(['git','show','1712a3a:helix-rew-tuner/scripts/pipeline.py']).decode('utf-8'),old.__file__,'exec'),old.__dict__)
f=measure.common_grid(20,20000,96);target=measure.load_target(root/'helix-rew-tuner/assets/default_incar_target.txt',f)
rng=np.random.default_rng(118); rows=[]
with tempfile.TemporaryDirectory() as tmp:
    for i in range(29):
        faults=[(float(rng.uniform(350,700)),float(rng.uniform(1.5,3)),float(rng.uniform(3,6))),
                (float(rng.uniform(1800,3000)),float(rng.uniform(1.5,3)),float(rng.uniform(2,4)))]
        dev=tunelib.cascade_db(f,faults)
        if i%3==1: dev+=tunelib.peaking_db(f,float(rng.uniform(800,1500)),8,-7)
        if i%3==2: dev+=tunelib.low_shelf_db(f,180,.7,float(rng.uniform(-3,3)))+tunelib.high_shelf_db(f,5000,.7,float(rng.uniform(-2,2)))
        dev+=rng.normal(0,.25,len(f))
        path=Path(tmp)/'capture.txt';path.write_text('\n'.join('%g %g'%(x,y) for x,y in zip(f,80+target+dev)),encoding='utf-8')
        args=argparse.Namespace(measurement=str(path),positions=None,target='default',voice=None,fit_band=None,max_bands=5,trust_band=None,gate_ms=None,session_tune=None,channels=None,capture='mmm',ambient=None,min_snr_db=10,cancel_check=None,accept_tilt=True,capture_profile=None,sittings=None,limits=None,partner=None)
        results=[]
        for module in (old,pipeline):
            report=module.propose(args);bank=report['proposal']['bands']
            if report.get('judging',{}).get('apply_recommendation')=='hold_for_review': bank=[]
            correction=tunelib.cascade_db(f,[(b['f_hz'],b['q'],b['gain_db']) for b in bank])
            results.append(tunelib.audibility_score(f,dev+correction,band=(60,12000)))
        rows.append({'case':i,'previous':round(results[0],4),'new':round(results[1],4),'improvement':round(results[0]-results[1],4)})
report={'cases':len(rows),'helped_over_0_1db':sum(r['improvement']>.1 for r in rows),'harmed_over_0_1db':sum(r['improvement']<-.1 for r in rows),'mean_score_gain':round(float(np.mean([r['improvement'] for r in rows])),4),'rows':rows}
print(json.dumps(report,indent=2))
if report['harmed_over_0_1db']: sys.exit(1)
