"""Helix channel Phase control: storage verified by controlled diff on a
P SIX DSP MK2 tune (PC-Tool 4.80b, 2026-10-01) -- the only change between
two saves was the channel's delay tag P="0" -> P="84.375" (degrees)."""

import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import afpx  # noqa: E402
import measure  # noqa: E402
import pipeline  # noqa: E402
import tunelib  # noqa: E402


# Real-file layout: the <T> tag lives INSIDE each channel's <OC> block.
REAL_LAYOUT = (
    '<ATF><OC ON="1" CINV="0">'
    '<Fil T="16" F="2600.00" Q="0.7" G="-24" dF="2600" FN="1" I="0" FilBy="0"/>'
    '<Fil T="17" F="3000.00" Q="2" G="-2" dF="3000" FN="2" I="0" FilBy="0"/>'
    '<Vol T="15" L="1.0" i="0"/><T T="209" P="0" PM="4"/></OC>'
    '<OC ON="1" CINV="0">'
    '<Fil T="16" F="20.00" Q="0.7" G="-24" dF="20" FN="3" I="0" FilBy="0"/>'
    '<Fil T="15" F="80.00" Q="0.7" G="-24" dF="80" FN="4" I="0" FilBy="0"/>'
    '<Fil T="17" F="50.00" Q="2" G="-2" dF="50" FN="5" I="0" FilBy="0"/>'
    '<Vol T="15" L="1.0" i="1"/><T T="182" P="0" PM="4"/></OC></ATF>'
)


def _encode(xml, path):
    payload = xml.encode('utf-8')
    Path(path).write_bytes(struct.pack('>I', len(payload)) + zlib.compress(payload, 9))


class PhaseReadWriteTests(unittest.TestCase):
    def test_channels_report_phase_and_reference(self):
        xml = REAL_LAYOUT.replace('P="0" PM="4"/></OC><OC', 'P="84.375" PM="4"/></OC><OC', 1)
        chans = afpx.channels(xml)
        self.assertEqual(chans[0]['phase_deg'], 84.375)
        self.assertEqual(chans[1]['phase_deg'], 0.0)
        self.assertEqual(chans[0]['phase_reference_hz'], 2600.0)

    def test_write_changes_only_p_on_the_one_channel(self):
        new = afpx.write_phase_rotation(REAL_LAYOUT, 0, 84.375)
        self.assertEqual(new, REAL_LAYOUT.replace('P="0"', 'P="84.375"', 1))
        result = afpx.verify_phase_write(REAL_LAYOUT, new, 0, 84.375)
        self.assertTrue(result['pass'], result['errors'])

    def test_whole_degrees_are_written_without_decimals(self):
        new = afpx.write_phase_rotation(REAL_LAYOUT, 1, 90.0)
        self.assertIn('<T T="182" P="90" PM="4"/>', new)
        back = afpx.write_phase_rotation(new, 1, 0.0)
        self.assertEqual(back, REAL_LAYOUT)

    def test_off_grid_and_out_of_range_angles_are_refused(self):
        for bad in (50.0, 360.0, -5.625, float('nan')):
            with self.subTest(angle=bad), self.assertRaises(ValueError):
                afpx.write_phase_rotation(REAL_LAYOUT, 0, bad)

    def test_a_tag_without_p_is_refused(self):
        xml = REAL_LAYOUT.replace(' P="0" PM="4"/></OC><OC', ' PM="4"/></OC><OC', 1)
        with self.assertRaisesRegex(ValueError, 'P='):
            afpx.write_phase_rotation(xml, 0, 84.375)

    def test_verify_catches_a_collateral_delay_change(self):
        new = afpx.write_phase_rotation(REAL_LAYOUT, 0, 84.375).replace('T="209"', 'T="210"')
        self.assertFalse(afpx.verify_phase_write(REAL_LAYOUT, new, 0, 84.375)['pass'])

    def test_lint_allows_phase_only_when_asked_and_never_a_delay(self):
        new = afpx.write_phase_rotation(REAL_LAYOUT, 0, 84.375)
        self.assertFalse(afpx.roundtrip_lint(REAL_LAYOUT, new)['pass'])
        self.assertTrue(afpx.roundtrip_lint(REAL_LAYOUT, new, allow_phase=True)['pass'])
        moved = new.replace('T="209"', 'T="210"')
        self.assertFalse(afpx.roundtrip_lint(REAL_LAYOUT, moved, allow_phase=True)['pass'])


class PhasePlanTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / 'source.afpx'
        self.output = self.root / 'output.afpx'
        _encode(REAL_LAYOUT, self.source)

    def plan(self, edits, confirmations):
        return {
            'version': 1, 'source_path': str(self.source),
            'source_sha256': hashlib.sha256(self.source.read_bytes()).hexdigest(),
            'format': 'afpx', 'output_path': str(self.output),
            'edits': edits, 'confirmations': confirmations,
        }

    def test_apply_writes_a_confirmed_phase_rotation(self):
        edit = {'id': 'phase-tw-l', 'kind': 'phase_rotation', 'channel': 0, 'degrees': 84.375}
        plan_path = self.root / 'plan.json'
        plan_path.write_text(json.dumps(self.plan([edit], {'phase-tw-l': True})), encoding='utf-8')
        manifest = pipeline.apply_plan(plan_path)
        self.assertEqual(afpx.decode(self.output),
                         REAL_LAYOUT.replace('P="0"', 'P="84.375"', 1))
        self.assertTrue(manifest['verification']['edits'][0]['result']['pass'])
        self.assertTrue(manifest['verification']['roundtrip_lint']['pass'])

    def test_unconfirmed_phase_rotation_is_refused(self):
        edit = {'id': 'p', 'kind': 'phase_rotation', 'channel': 0, 'degrees': 84.375}
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            pipeline.validate_plan(self.plan([edit], {}), self.source)

    def test_phase_rotation_is_phase_domain_and_cannot_join_eq(self):
        edits = [{'id': 'p', 'kind': 'phase_rotation', 'channel': 0, 'degrees': 84.375},
                 {'id': 'q', 'kind': 'filter_slot', 'channel': 0, 'slot': 1, 'G': -3.0}]
        with self.assertRaisesRegex(ValueError, 'phase-domain'):
            pipeline.validate_plan(self.plan(edits, {'p': True, 'q': True}), self.source)

    def test_no_op_and_off_grid_rotations_are_refused(self):
        for degrees, pattern in ((0.0, 'no-op'), (50.0, 'grid')):
            edit = {'id': 'p', 'kind': 'phase_rotation', 'channel': 0, 'degrees': degrees}
            with self.subTest(degrees=degrees), self.assertRaisesRegex(ValueError, pattern):
                pipeline.validate_plan(self.plan([edit], {'p': True}), self.source)
        self.assertFalse(self.output.exists())


class PhaseModelCheckTests(unittest.TestCase):
    """Two solo sweeps of one driver -- Phase 0 and Phase N, same mic and
    timing reference -- confirm (or refute) that this unit builds the Q=1
    all-pass the ULTRA S was measured to build."""

    def setUp(self):
        self.freqs = measure.common_grid(20.0, 20000.0, 96)
        x = (self.freqs / 2600.0) ** 2
        self.before = 10 ** (-12 / 20) * (x / (1 + x)) * np.exp(-2j * np.pi * self.freqs * 2.2e-3)

    def test_matching_unit_reads_as_consistent(self):
        after = self.before * tunelib.helix_phase_rotation_H(self.freqs, 84.375, 2600.0, 96000.0)
        r = tunelib.phase_control_check(self.freqs, self.before, after, 84.375, 2600.0, 96000.0)
        self.assertLess(r['rms_error_deg'], 1.0)
        self.assertTrue(r['consistent'])
        self.assertAlmostEqual(r['measured_at_reference_deg'], 84.375, delta=1.0)

    def test_a_different_filter_is_caught(self):
        other = tunelib.allpass_H(self.freqs, 4384.1, Q=0.5, order=2, fs=96000.0)
        r = tunelib.phase_control_check(self.freqs, self.before, self.before * other,
                                        84.375, 2600.0, 96000.0)
        self.assertFalse(r['consistent'])


class ChannelTypeRuleTests(unittest.TestCase):
    """Audiotec Fischer knowledge base: fine phase (5.625 deg steps) exists only
    on channels defined as subwoofer or mid/high in a fully active system;
    "low" and "fullrange" channels get polarity only. On the user's tune PM
    was 4 on exactly the High and Subwoofer channels and 1 on Low and Full."""

    LOW_CHANNEL = REAL_LAYOUT.replace('<T T="182" P="0" PM="4"/>', '<T T="182" P="0" PM="1"/>')

    def test_channels_flag_where_fine_phase_exists(self):
        chans = afpx.channels(self.LOW_CHANNEL)
        self.assertTrue(chans[0]['fine_phase_available'])
        self.assertFalse(chans[1]['fine_phase_available'])

    def test_write_is_refused_on_a_polarity_only_channel(self):
        with self.assertRaisesRegex(ValueError, 'polarity only'):
            afpx.write_phase_rotation(self.LOW_CHANNEL, 1, 84.375)

    def test_plan_refuses_a_polarity_only_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 's.afpx'
            _encode(self.LOW_CHANNEL, source)
            plan = {'version': 1, 'source_path': str(source),
                    'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'format': 'afpx', 'output_path': str(Path(tmp) / 'o.afpx'),
                    'edits': [{'id': 'p', 'kind': 'phase_rotation', 'channel': 1,
                               'degrees': 84.375}],
                    'confirmations': {'p': True}}
            with self.assertRaisesRegex(ValueError, 'polarity only'):
                pipeline.validate_plan(plan, source)


if __name__ == '__main__':
    unittest.main()
