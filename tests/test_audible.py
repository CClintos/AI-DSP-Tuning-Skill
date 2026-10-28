import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'helix-rew-tuner' / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import audible
import judging
import measure
import pipeline
import tunelib

F = measure.common_grid(20, 20000, 96)


class AudibleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def trace(self, name, db, phase=None, timed=True, axis=None):
        f = F if axis is None else axis
        head = '* timing reference: Acoustic\n' if timed else '* capture with no timing metadata\n'
        rows = ['%g %g' % (x, y) + ('' if phase is None else ' %g' % z)
                for x, y, z in zip(f, db, np.zeros(len(f)) if phase is None else phase)]
        p = self.root / name
        p.write_text(head + '\n'.join(rows), encoding='utf-8')
        return str(p)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / 'pipeline.py'), *args],
                              text=True, capture_output=True, cwd=self.root)

    def quality(self, distortion=False, mismatched=False):
        normal = self.trace('normal.txt', F * 0 + 80)
        if not distortion:
            loud = self.trace('loud.txt', F * 0 + 84)
            spec = {'version': 1, 'level_steps': [{'path': normal, 'level_db': 0}, {'path': loud, 'level_db': 6}]}
        else:
            new = self.trace('new.txt', F * 0 + (83 if mismatched else 80))
            h = self.trace('h.txt', F * 0 + 40)
            nh = self.trace('newh.txt', F * 0 + 45)
            noise = self.trace('noise.txt', F * 0 + 10)
            spec = {'version': 1, 'distortion': {'fundamental': new, 'harmonics': {'h3': nh}, 'noise': noise},
                    'distortion_reference': {'fundamental': normal, 'harmonics': {'h3': h}, 'noise': noise}}
        report = judging.load_spec(spec, self.root)
        out = self.root / 'limits.json'
        out.write_text(json.dumps(report), encoding='utf-8')
        return str(out), report

    def test_compression_and_distortion_become_actual_boost_limits(self):
        for distortion in (False, True):
            path, _report = self.quality(distortion)
            cap, blocked = audible.load_limits(path, F)
            self.assertTrue(blocked)
            self.assertEqual(0, cap[np.argmin(abs(F - 1000))])

    def test_distortion_at_different_output_level_does_not_invent_capacity_loss(self):
        path, report = self.quality(True, True)
        cap, blocked = audible.load_limits(path, F)
        self.assertFalse(blocked)
        self.assertTrue(np.all(cap == 3))
        self.assertEqual('unmatched_level', report['evidence']['distortion']['comparison'][0]['status'])

    def test_ceiling_changes_single_and_robust_fitting(self):
        dev = tunelib.peaking_db(F, 1000, 2, -5)
        for runs in (1, 2):
            if runs == 1:
                bands, _ = tunelib.fit_peq(F, dev, (300, 4000), boost_ceiling_db=F * 0, cut_seed_retry=True)
            else:
                bands, _ = tunelib.fit_peq_robust(F, np.vstack([dev, dev]), (300, 4000), boost_ceiling_db=F * 0)
            self.assertLessEqual(float(np.max(tunelib.cascade_db(F, bands))), .1)

    def test_refinement_cannot_remove_a_cut_when_that_exceeds_measured_capacity(self):
        old = [(1000, 2, -5)]
        report = tunelib.refine_bank(F, [tunelib.cascade_db(F, old)], old, (300, 4000),
                                    fixed_anchor=True, boost_ceiling_db=F * 0)
        delta = tunelib.cascade_db(F, report['bank']) - tunelib.cascade_db(F, old)
        self.assertLessEqual(float(np.max(delta)), .1)

    def test_fixed_refinement_and_judge_keep_identical_level_reference(self):
        old = [(1000, 1.5, -4)]
        dev = tunelib.cascade_db(F, old)
        report = tunelib.refine_bank(F, [dev], old, (300, 4000), fixed_anchor=True)
        self.assertTrue(report['edits'])
        delta = tunelib.cascade_db(F, report['bank']) - tunelib.cascade_db(F, old)
        judged = judging.scorecard(F, dev, dev + delta, (F >= 300) & (F <= 4000))
        self.assertNotEqual('regressed', judged['verdict'])

    def test_cli_limits_block_ungated_boost_trials(self):
        limits, _ = self.quality()
        target = measure.load_target(SCRIPTS.parent / 'assets/default_incar_target.txt', F)
        capture = self.trace('mmm.txt', 80 + target + tunelib.peaking_db(F, 1000, 2, -5))
        run = self.cli('propose', '--capture', 'mmm', '--measurement', capture,
                       '--target', 'default', '--limits', limits)
        self.assertEqual(0, run.returncode, run.stderr)
        result = json.loads(run.stdout)
        all_bands = result['proposal']['bands'] + result['proposal']['needs_trial']
        eq = tunelib.cascade_db(F, [(b['f_hz'], b['q'], b['gain_db']) for b in all_bands])
        self.assertLessEqual(float(np.max(eq)), .1)
        self.assertTrue(result['judging']['evidence']['limits'])

    def test_partner_does_not_copy_a_dip_or_invent_a_boost(self):
        target = measure.load_target(SCRIPTS.parent / 'assets/default_incar_target.txt', F)
        own = self.trace('own.txt', 80 + target)
        other = self.trace('other.txt', 80 + target + tunelib.peaking_db(F, 1200, 3, -8))
        run = self.cli('propose', '--capture', 'mmm', '--measurement', own,
                       '--target', 'default', '--partner', other)
        self.assertEqual(0, run.returncode, run.stderr)
        report = json.loads(run.stdout)
        self.assertFalse(report['proposal']['bands'])
        self.assertFalse(report['proposal']['needs_trial'])

    def test_partner_constraint_reduces_excess_on_louder_side(self):
        target = measure.load_target(SCRIPTS.parent / 'assets/default_incar_target.txt', F)
        own = self.trace('own.txt', 80 + target + tunelib.peaking_db(F, 1200, 2, 5))
        other = self.trace('other.txt', 80 + target)
        run = self.cli('propose', '--capture', 'mmm', '--measurement', own,
                       '--target', 'default', '--partner', other)
        self.assertEqual(0, run.returncode, run.stderr)
        balance = json.loads(run.stdout)['judging']['partner_balance']
        self.assertLess(balance['after_mismatch_db'], balance['before_mismatch_db'])

    def test_measured_voice_match_uses_actual_change_and_protects_inputs(self):
        baseline = self.trace('base.txt', F * 0 + 80)
        candidate = self.trace('trial.txt', F * 0 + 83)
        run = self.cli('voice-match', '--baseline', baseline, '--candidates', 'warm=' + candidate)
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertAlmostEqual(3, json.loads(run.stdout)['variants'][0]['measured_loudness_change_db'], places=2)
        original = Path(candidate).read_bytes()
        run = self.cli('voice-match', '--baseline', baseline, '--candidates', 'warm=' + candidate, '--out', candidate)
        self.assertEqual(2, run.returncode)
        self.assertEqual(original, Path(candidate).read_bytes())

    def bass(self, timed=True, together_offset=0):
        low = tunelib.crossover_H(F, 'lp', 'LR', 24, 100)
        high = tunelib.crossover_H(F, 'hp', 'LR', 24, 100)
        delayed = low * np.exp(-2j * np.pi * F * .001)
        paths = [self.trace('sub.txt', 80 + 20 * np.log10(abs(delayed)), np.angle(delayed, deg=True), timed),
                 self.trace('front.txt', 80 + 20 * np.log10(abs(high)), np.angle(high, deg=True), timed),
                 self.trace('sum.txt', 80 + together_offset + 20 * np.log10(abs(delayed + high)))]
        target = self.trace('target.txt', 20 * np.log10(abs(low + high)))
        return paths, target

    def test_bass_trial_finds_alignment_without_maximizing_output(self):
        paths, target = self.bass()
        run = self.cli('bass-trials', '--sub', paths[0], '--front', paths[1], '--together', paths[2],
                       '--target', target, '--delays-ms', '-1', '0', '1', '--gains-db', '0')
        self.assertEqual(0, run.returncode, run.stderr)
        result = json.loads(run.stdout)
        self.assertEqual(-1, result['candidate']['delay_change_ms'])
        self.assertTrue(result['predicted_not_measured'])

    def test_bass_trials_refuse_unknown_time_base_and_inconsistent_sum(self):
        for timed, offset in ((False, 0), (True, 4)):
            paths, target = self.bass(timed, offset)
            run = self.cli('bass-trials', '--sub', paths[0], '--front', paths[1], '--together', paths[2], '--target', target)
            self.assertEqual(2, run.returncode, run.stdout + run.stderr)


    def test_joint_stereo_uses_shared_cuts_and_preserves_the_healthy_side(self):
        target = measure.load_target(SCRIPTS.parent / 'assets/default_incar_target.txt', F)
        common = tunelib.peaking_db(F, 650, 2, 4)
        left = self.trace('left.txt', 80 + target + common + tunelib.peaking_db(F, 2200, 2, 4))
        right = self.trace('right.txt', 80 + target + common)
        run = self.cli('stereo-propose', '--left', left, '--right', right, '--max-bands', '2')
        self.assertEqual(0, run.returncode, run.stderr)
        report = json.loads(run.stdout)
        self.assertTrue(report['common_bands'])
        self.assertLess(report['after_lr_mismatch_db'], report['before_lr_mismatch_db'])
        self.assertFalse(report['independent_repeats'])
        self.assertTrue(all(b[2] <= 0 for b in report['common_bands'] + report['side_bands']['left'] + report['side_bands']['right']))

    def test_validated_anchor_rejects_disagreeing_reference_bands(self):
        target = F * 0
        peaked = 80 + tunelib.cascade_db(F, [(500, 2, 5), (2500, 1.5, 3)])
        self.assertAlmostEqual(80, tunelib.validated_anchor_offset(F, peaked, target), delta=.3)
        tilted = peaked + tunelib.low_shelf_db(F, 300, .7, 4)
        self.assertEqual(tunelib.target_anchor_offset(F, tilted, target), tunelib.validated_anchor_offset(F, tilted, target))
        support = ((F > 300) & (F < 3000)).astype(float)
        self.assertEqual(tunelib.target_anchor_offset(F, peaked, target, confidence=support), tunelib.validated_anchor_offset(F, peaked, target, confidence=support))

    def test_anchor_is_invariant_to_source_gain(self):
        curve = tunelib.cascade_db(F, [(500, 2, 5), (2500, 1.5, 3)])
        for offset in (40, 80, 110):
            anchor = tunelib.validated_anchor_offset(F, curve + offset, F * 0)
            self.assertAlmostEqual(offset, anchor, delta=.3)

    def test_broad_presence_variant_uses_a_free_peq_slot(self):
        import afpx
        channel = '<OC ON="1" CINV="0"><Fil T="1" F="1000" Q="1" G="0" dF="1000" FN="1" I="0" FilBy="0"/></OC>'
        tune = self.root / 'tune.afpx'
        afpx._encode_unchecked('<ATF>' + channel + '</ATF>', str(tune))
        run = self.cli('voice-variants', '--afpx', str(tune), '--out-dir', str(self.root / 'variants'),
                       '--presence-channels', '0', '--presence-db', '-1')
        self.assertEqual(0, run.returncode, run.stderr)
        edit = json.loads(run.stdout)['variants'][0]['edits'][0]
        self.assertEqual('17', edit['type_code'])
        self.assertEqual(-1, edit['G'])
        self.assertFalse(list((self.root / 'variants').glob('*.afpx')))


    def test_tonal_junction_guard_vetoes_a_worse_handover(self):
        low = tunelib.crossover_H(F, 'lp', 'LR', 24, 100)
        high = tunelib.crossover_H(F, 'hp', 'LR', 24, 100)
        sub = self.trace('sub.txt', 80 + 20 * np.log10(abs(low)), np.angle(low, deg=True))
        front = self.trace('front.txt', 80 + 20 * np.log10(abs(high)), np.angle(high, deg=True))
        path = self.root / 'junction.json'
        path.write_text(json.dumps({'dsp_sample_rate_hz': 96000, 'drivers': {'sub': sub, 'front': front},
                                    'junctions': [{'lower': 'sub', 'upper': 'front', 'crossover_hz': 100}],
                                    'apply_to': ['sub']}))
        result = audible.junction_guard(argparse.Namespace(junction_spec=str(path)), [(100, .7, -9)], pipeline.probe)
        self.assertEqual('hold_for_review', result['status'])
        self.assertEqual(1, result['positions'])

    def test_shared_tonal_filter_preserves_the_handover(self):
        low = tunelib.crossover_H(F, 'lp', 'LR', 24, 100)
        high = tunelib.crossover_H(F, 'hp', 'LR', 24, 100)
        sub = self.trace('sub.txt', 80 + 20 * np.log10(abs(low)), np.angle(low, deg=True))
        front = self.trace('front.txt', 80 + 20 * np.log10(abs(high)), np.angle(high, deg=True))
        path = self.root / 'junction.json'
        path.write_text(json.dumps({'dsp_sample_rate_hz': 96000, 'drivers': {'sub': sub, 'front': front},
                                    'junctions': [{'lower': 'sub', 'upper': 'front', 'crossover_hz': 100}],
                                    'apply_to': ['sub', 'front']}))
        result = audible.junction_guard(argparse.Namespace(junction_spec=str(path)), [(100, .7, -9)], pipeline.probe)
        self.assertEqual('assessed', result['status'])
        self.assertEqual('unknown', audible.junction_guard(argparse.Namespace(), [], pipeline.probe)['status'])


    def test_stereo_pure_level_offset_gets_a_trim_without_eq(self):
        target = measure.load_target(SCRIPTS.parent / 'assets/default_incar_target.txt', F)
        left = self.trace('left.txt', 82 + target)
        right = self.trace('right.txt', 80 + target)
        run = self.cli('stereo-propose', '--left', left, '--right', right)
        self.assertEqual(0, run.returncode, run.stderr)
        report = json.loads(run.stdout)
        self.assertEqual({'side': 'left', 'trim_db': -2}, report['level_trim'])
        self.assertFalse(report['common_bands'])
        self.assertFalse(report['side_bands']['left'])
        self.assertFalse(report['side_bands']['right'])
        self.assertAlmostEqual(2, report['before_lr_mismatch_db'], places=2)
        self.assertAlmostEqual(0, report['after_lr_mismatch_db'], places=2)
        self.assertNotEqual('regressed', report['judging']['verdict'])
        diagnostic = tunelib.lr_match_cuts(F, 82 + target, 80 + target, target_db=target)
        self.assertAlmostEqual(2, diagnostic['raw_wrms_before_db'], places=2)
        self.assertAlmostEqual(0, diagnostic['trimmed_wrms_before_db'], places=2)


if __name__ == '__main__':
    unittest.main()
