"""Read-only REW HTTP API bridge, tested against a local stub that serves the
wire shapes documented (and verified live against REW 5.40) by the MIT
projects alex-vyverman/OptiMIMO and brandon-fryslie/room-eq-wizard-mcp:
GET /measurements keyed by 1-based index, base64 BIG-endian float32 arrays,
bare NaN literals, IR start time on the timing-reference axis."""

import base64
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np


SCRIPTS = Path(__file__).resolve().parents[1] / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import measure  # noqa: E402
import rew_api  # noqa: E402


def _b64(values):
    return base64.b64encode(np.asarray(values, dtype='>f4').tobytes()).decode('ascii')


FS = 48000
START_TIME = -0.0105          # REW keeps a lead-in before the arrival
ARRIVAL = 0.0035              # seconds after the timing reference
IR = np.zeros(int(0.4 * FS))
IR[int(round((ARRIVAL - START_TIME) * FS))] = 1.0
IR[int(round((ARRIVAL - START_TIME) * FS)) + int(0.003 * FS)] = 0.5
FR_START, FR_PPO, FR_N = 20.0, 96, 958
FR_F = FR_START * 2 ** (np.arange(FR_N) / FR_PPO)
FR_MAG = 80.0 + 3.0 * np.sin(np.log2(FR_F))
FR_PHASE = np.degrees(np.angle(np.exp(-2j * np.pi * FR_F * 1e-3)))

MEASUREMENTS = ('{"1": {"uuid": "aaa-111", "title": "FL tweeter", "sampleRate": 48000, '
                '"timingReference": "Acoustic", "signalToNoisedB": 52.5, "startFreq": 20.0, '
                '"endFreq": 20000.0},'
                ' "2": {"uuid": "bbb-222", "title": "FL mid", "sampleRate": 48000, '
                '"signalToNoisedB": NaN}}')


class _Stub(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def _send(self, body, status=200):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        _Stub.seen.append(('GET', url.path, parse_qs(url.query)))
        if url.path == '/measurements':
            return self._send(MEASUREMENTS)
        if url.path == '/measurements/aaa-111/frequency-response':
            return self._send(json.dumps({'unit': 'SPL', 'smoothing': '1/48', 'startFreq': FR_START,
                                          'ppo': FR_PPO, 'magnitude': _b64(FR_MAG),
                                          'phase': _b64(FR_PHASE)}))
        if url.path == '/measurements/aaa-111/impulse-response':
            return self._send(json.dumps({'startTime': START_TIME, 'sampleInterval': 1.0 / FS,
                                          'sampleRate': FS, 'timingReference': 'Acoustic',
                                          'data': _b64(IR)}))
        if url.path == '/measurements/bbb-222/impulse-response':
            return self._send('{"message": "Measurement has no impulse response"}')
        return self._send('{"message": "not found"}', status=404)

    def do_POST(self):
        _Stub.seen.append(('POST', self.path, None))
        self._send('{}')


class RewApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), _Stub)
        cls.url = 'http://127.0.0.1:%d' % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _Stub.seen.clear()
        self.client = rew_api.RewClient(self.url)

    def test_lists_measurements_in_index_order_with_nan_as_none(self):
        items = self.client.list_measurements()
        self.assertEqual([m['title'] for m in items], ['FL tweeter', 'FL mid'])
        self.assertEqual(items[0]['index'], 1)
        self.assertEqual(items[0]['signal_to_noise_db'], 52.5)
        self.assertIsNone(items[1]['signal_to_noise_db'])

    def test_resolves_by_title_index_or_uuid(self):
        for ref in ('FL tweeter', '1', 'aaa-111'):
            self.assertEqual(self.client.resolve(ref)['uuid'], 'aaa-111')
        with self.assertRaisesRegex(rew_api.RewError, 'no measurement'):
            self.client.resolve('rear')

    def test_frequency_response_decodes_big_endian_and_builds_the_axis(self):
        f, spl, phase, meta = self.client.frequency_response('FL tweeter')
        self.assertTrue(np.allclose(f, FR_F, rtol=1e-6))
        self.assertTrue(np.allclose(spl, FR_MAG, atol=1e-4))
        self.assertTrue(np.allclose(phase, FR_PHASE, atol=1e-3))
        self.assertEqual(meta['smoothing'], '1/48')
        self.assertEqual(_Stub.seen[-1][2].get('ppo'), ['96'])

    def test_impulse_response_keeps_the_timing_reference_start(self):
        samples, fs, start, meta = self.client.impulse_response('FL tweeter')
        self.assertEqual(fs, FS)
        self.assertAlmostEqual(start, START_TIME)
        self.assertEqual(meta['timing_reference'], 'Acoustic')
        self.assertEqual(_Stub.seen[-1][2].get('normalised'), ['false'])

    def test_a_measurement_without_an_ir_says_so(self):
        with self.assertRaisesRegex(rew_api.RewError, 'no impulse response'):
            self.client.impulse_response('FL mid')

    def test_bridge_is_read_only(self):
        self.client.list_measurements()
        self.client.frequency_response('FL tweeter')
        self.client.impulse_response('FL tweeter')
        self.assertTrue(all(method == 'GET' for method, _p, _q in _Stub.seen))

    def test_unreachable_rew_gives_an_actionable_error(self):
        dead = rew_api.RewClient('http://127.0.0.1:9', timeout=1.0)
        with self.assertRaisesRegex(rew_api.RewError, 'API'):
            dead.list_measurements()

    def test_cli_exports_full_and_direct_sound_text_the_tools_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / 'tw.txt'
            direct = Path(tmp) / 'tw_direct.txt'
            for extra, out in (([], full), (['--direct-sound'], direct)):
                run = subprocess.run([sys.executable, str(SCRIPTS / 'rew_api.py'), '--url', self.url,
                                      'export', 'FL tweeter', '--out', str(out)] + extra,
                                     text=True, capture_output=True, check=False)
                self.assertEqual(0, run.returncode, run.stdout + run.stderr)
            f, spl, phase, _ = measure.load_text_export(str(full))
            self.assertIsNotNone(phase)
            self.assertIn('Acoustic', full.read_text(encoding='utf-8'))
            f2, spl2, phase2, _ = measure.load_text_export(str(direct))
            sel = (f2 > 5000) & (f2 < 5400)
            slope = np.polyfit(2 * np.pi * f2[sel], np.unwrap(np.radians(phase2[sel])), 1)[0]
            self.assertAlmostEqual(-slope, ARRIVAL, delta=2e-5)
            sel = (f2 > 5000) & (f2 < 8000)
            self.assertLess(float(np.max(spl2[sel]) - np.min(spl2[sel])), 1.0)


if __name__ == '__main__':
    unittest.main()
