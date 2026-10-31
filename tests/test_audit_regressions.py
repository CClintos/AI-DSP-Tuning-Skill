import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'helix-rew-tuner'/'scripts'))
import measure
import tunelib as t
import pipeline
import judging
import corpus


class AuditRegressionTests(unittest.TestCase):
    def test_unmeasured_bass_is_inconclusive(self):
        f = measure.common_grid(20, 20000, 96)
        r = t.predicted_vs_measured(f, np.full(len(f),80.), np.full(len(f),80.),
              [(80,1,3)], support=(f>=500)&(f<=10000))
        self.assertEqual('inconclusive', r['bands'][0]['verdict'])
        self.assertEqual(0, r['bands'][0]['confidence'])

    def test_internal_support_hole_cannot_certify_presence(self):
        f = measure.common_grid(20, 20000, 96)
        live = ~((f>1100)&(f<3900))
        rows = list(judging.regions(f, live))
        self.assertFalse(next(r[-1] for r in rows if r[0]=='presence'))

    def test_listening_log_collision_duplicate_and_exact_p(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            key = root/'key.json'
            key.write_text(json.dumps({'labels': {'X':{'is':'A','source':'a'},'Y':{'is':'B','source':'b'}}}))
            args = SimpleNamespace(key=str(key),choices=['X']*8+['Y']*2,note=None,context=None,out=str(root/'ab_log.json'))
            with self.assertRaisesRegex(ValueError,'overwrite'):
                pipeline.ab_result(args)
            self.assertFalse((root/'ab_log.json').exists())
            args.out = None
            r = pipeline.ab_result(args)
            self.assertIsNone(r['preferred'])
            self.assertAlmostEqual(.109, r['p_chance'], places=3)
            pipeline.ab_result(args)
            self.assertEqual(1,len(json.loads((root/'ab_log.json').read_text())))

    def test_corpus_same_recording_different_exports_rejected(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            captures=[]
            for i in range(2):
                path=root/('half%d.txt'%i)
                path.write_text('* capture_id: same-recording\n'+'\n'.join('%g %g'%(x,80+i) for x in np.geomspace(20,20000,20)))
                captures.append({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            spec={'version':1,'sessions':[{'session_id':'s','vehicle_id':'v','listener_id':'l','before':[captures[0]],'after':[captures[1]]}]}
            with self.assertRaisesRegex(ValueError,'recording was counted'):
                corpus.replay(spec,td)

    def test_vehicle_guard_blocks_joint_relaxation(self):
        import stereo_refine
        f=measure.common_grid(20,20000,24)
        d=t.peaking_db(f,2500,2,-6,fs=48000)
        w=.01*np.sin(np.log(f)*4)
        check=pipeline.guard_move_check({'no_boost':[{'lo_hz':2200,'hi_hz':2800,'channels':[0],'reason':'physical null'}]},[0],f,48000)
        r=stereo_refine.refine_pair(f,[[80+d+w,80+d-w]]*2,np.zeros(len(f)),[[(2500,2,-6)]]*2,np.ones(len(f),bool),(700,5000),48000,2,move_checks=[check,check])
        self.assertTrue(r['unchanged'])
