import hashlib
import gc
import json
import subprocess
import sys
import tempfile
import unittest
import warnings
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "helix-rew-tuner" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import afpx  # noqa: E402
import pipeline  # noqa: E402


SYNTHETIC_AFPX = (
    '<ATF><OC ON="1" CINV="0">'
    '<Fil T="16" F="80.00" Q="0.7" G="-24" dF="80" FN="1" I="0" FilBy="0"/>'
    '<Fil T="17" F="100.00" Q="1" G="-2" dF="100" FN="2" I="0" FilBy="0"/>'
    '<Fil T="1" F="200.00" Q="1" G="0" dF="200" FN="3" I="0" FilBy="0"/>'
    '<Fil T="1" F="25.00" Q="1" G="0" dF="25" FN="4" I="0" FilBy="0"/>'
    '<Vol T="15" L="1.0" i="0"/>'
    '<T PM="1" P="0" T="0"/>'
    '</OC></ATF>'
)


class PipelineApplyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.source = self.root / "source.afpx"
        self.output = self.root / "output.afpx"
        afpx.encode(SYNTHETIC_AFPX, self.source)

    def plan(self):
        return {
            "version": 1,
            "source_path": str(self.source),
            "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
            "format": "afpx",
            "output_path": str(self.output),
            "edits": [],
            "confirmations": {},
        }

    def peq_plan(self):
        plan = self.plan()
        plan["edits"] = [{
            "id": "peq-1",
            "kind": "filter_slot",
            "channel": 0,
            "slot": 1,
            "G": -3.0,
        }]
        return plan

    def test_validate_plan_refuses_source_hash_mismatch_without_writing(self):
        plan = self.peq_plan()
        plan["source_sha256"] = "0" * 64

        validator = getattr(pipeline, "validate_plan", None)
        self.assertIsNotNone(validator, "pipeline.validate_plan must exist")
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            validator(plan, self.source)

        self.assertFalse(self.output.exists())

    def test_validate_plan_refuses_output_equal_to_source_without_writing(self):
        plan = self.peq_plan()
        plan["output_path"] = str(self.source)
        before = self.source.read_bytes()

        with self.assertRaisesRegex(ValueError, "output_path.*source"):
            pipeline.validate_plan(plan, self.source)

        self.assertEqual(self.source.read_bytes(), before)

    def test_validate_plan_refuses_illegal_peq_limits_without_writing(self):
        plan = self.plan()
        plan["edits"] = [{
            "id": "peq-1",
            "kind": "filter_slot",
            "channel": 0,
            "slot": 1,
            "type_code": "17",
            "F": 100.0,
            "Q": 16.0,
            "G": -3.0,
        }]

        with self.assertRaisesRegex(ValueError, "Q 16.*0.5..15"):
            pipeline.validate_plan(plan, self.source)

        self.assertFalse(self.output.exists())

    def test_validate_plan_refuses_filter_slot_targeting_crossover(self):
        plan = self.plan()
        plan["edits"] = [{
            "id": "xover-1",
            "kind": "filter_slot",
            "channel": 0,
            "slot": 0,
            "F": 90.0,
        }]

        with self.assertRaisesRegex(ValueError, "crossover.*refus"):
            pipeline.validate_plan(plan, self.source)

        self.assertFalse(self.output.exists())

    def test_validate_plan_refuses_unconfirmed_output_trim(self):
        plan = self.plan()
        plan["edits"] = [{
            "id": "trim-1",
            "kind": "output_trim",
            "channel": 0,
            "trim_db": -1.5,
        }]

        with self.assertRaisesRegex(ValueError, "trim-1.*confirmation"):
            pipeline.validate_plan(plan, self.source)

        self.assertFalse(self.output.exists())

    def test_validate_plan_refuses_unconfirmed_delay(self):
        plan = self.plan()
        plan["edits"] = [{
            "id": "delay-1",
            "kind": "delay_samples",
            "channel": 0,
            "samples": 96,
        }]

        with self.assertRaisesRegex(ValueError, "delay-1.*confirmation"):
            pipeline.validate_plan(plan, self.source)

        self.assertFalse(self.output.exists())

    def test_validate_plan_refuses_unconfirmed_shelf_and_allpass_edits(self):
        cases = [
            ("shelf-1", 3, "3", {"F": 80.0, "Q": 0.7, "G": 2.0}),
            ("apf-1", 2, "20", {"F": 400.0, "Q": 2.0, "G": 0.0}),
        ]
        for edit_id, slot, type_code, values in cases:
            with self.subTest(edit_id=edit_id):
                plan = self.plan()
                plan["edits"] = [{
                    "id": edit_id,
                    "kind": "filter_slot",
                    "channel": 0,
                    "slot": slot,
                    "type_code": type_code,
                    **values,
                }]

                with self.assertRaisesRegex(ValueError, "%s.*confirmation" % edit_id):
                    pipeline.validate_plan(plan, self.source)

                self.assertFalse(self.output.exists())

    def test_validate_plan_rejects_malformed_or_unsupported_schema(self):
        cases = []

        wrong_version = self.peq_plan()
        wrong_version["version"] = 2
        cases.append(("wrong version", wrong_version))

        missing_format = self.peq_plan()
        del missing_format["format"]
        cases.append(("missing required field", missing_format))

        unsupported_format = self.peq_plan()
        unsupported_format["format"] = "pct6"
        cases.append(("unsupported format", unsupported_format))

        wrong_source = self.peq_plan()
        wrong_source["source_path"] = str(self.root / "different.afpx")
        cases.append(("source path disagreement", wrong_source))

        empty_edits = self.plan()
        cases.append(("empty edits", empty_edits))

        edits_not_list = self.peq_plan()
        edits_not_list["edits"] = {}
        cases.append(("edits not list", edits_not_list))

        confirmations_not_object = self.peq_plan()
        confirmations_not_object["confirmations"] = []
        cases.append(("confirmations not object", confirmations_not_object))

        unknown_kind = self.peq_plan()
        unknown_kind["edits"][0]["kind"] = "crossover"
        cases.append(("unknown or crossover kind", unknown_kind))

        duplicate_ids = self.peq_plan()
        duplicate_ids["edits"].append(dict(duplicate_ids["edits"][0]))
        cases.append(("duplicate edit id", duplicate_ids))

        unknown_top = self.peq_plan()
        unknown_top["typo"] = True
        cases.append(("unknown top-level field", unknown_top))

        unknown_edit = self.peq_plan()
        unknown_edit["edits"][0]["gain"] = -4.0
        cases.append(("unknown edit field", unknown_edit))

        unused_confirmation = self.peq_plan()
        unused_confirmation["confirmations"] = {"typo-id": True}
        cases.append(("confirmation for unknown edit", unused_confirmation))

        shelf_in_middle = self.peq_plan()
        shelf_in_middle["edits"] = [{
            "id": "shelf-middle",
            "kind": "filter_slot",
            "channel": 0,
            "slot": 2,
            "type_code": "3",
            "F": 80.0,
            "Q": 0.7,
            "G": 2.0,
        }]
        shelf_in_middle["confirmations"] = {"shelf-middle": True}
        cases.append(("low shelf outside dF 25 slot", shelf_in_middle))

        for name, plan in cases:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    pipeline.validate_plan(plan, self.source)

        self.output.write_bytes(b"do not overwrite")
        with self.assertRaisesRegex(ValueError, "output_path.*exist"):
            pipeline.validate_plan(self.peq_plan(), self.source)
        self.assertEqual(self.output.read_bytes(), b"do not overwrite")

    def test_validate_plan_refuses_delay_and_filter_edit_on_same_channel(self):
        plan = self.peq_plan()
        plan["edits"].append({
            "id": "delay-1",
            "kind": "delay_samples",
            "channel": 0,
            "samples": 96,
        })
        plan["confirmations"] = {"delay-1": True}

        with self.assertRaisesRegex(ValueError, "delay.*filter.*same channel"):
            pipeline.validate_plan(plan, self.source)

        self.assertFalse(self.output.exists())

    def test_apply_plan_writes_new_verified_afpx_for_one_slot_edit(self):
        plan = self.peq_plan()
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        source_before = self.source.read_bytes()

        applier = getattr(pipeline, "apply_plan", None)
        self.assertIsNotNone(applier, "pipeline.apply_plan must exist")
        manifest = applier(plan_path)

        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertTrue(self.output.is_file())
        output_xml = afpx.decode(self.output)
        self.assertEqual(afpx.attrs(afpx.filters(afpx.channel_blocks(output_xml)[0])[1])["G"], "-3")
        self.assertEqual(manifest["plan_version"], 1)
        self.assertEqual(manifest["format"], "afpx")
        self.assertEqual(manifest["source_sha256"], hashlib.sha256(source_before).hexdigest())
        self.assertEqual(
            manifest["output_sha256"],
            hashlib.sha256(self.output.read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["normalized_edits"], [{
            "id": "peq-1",
            "kind": "filter_slot",
            "channel": 0,
            "slot": 1,
            "G": -3.0,
        }])
        self.assertTrue(manifest["verification"]["edits"][0]["result"]["pass"])
        self.assertTrue(manifest["verification"]["roundtrip_lint"]["pass"])
        self.assertEqual(manifest["verification"]["roundtrip_lint"]["slots_changed"], 1)
        self.assertIs(manifest["predicted_not_measured"], True)

    def test_afpx_codec_closes_files_without_resource_warnings(self):
        path = self.root / "codec.afpx"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            afpx.encode(SYNTHETIC_AFPX, path)
            self.assertEqual(afpx.decode(path), SYNTHETIC_AFPX)
            gc.collect()

        resource_warnings = [w for w in caught if issubclass(w.category, ResourceWarning)]
        self.assertEqual(resource_warnings, [])

    def test_plan_and_apply_cli_create_draft_then_emit_manifest(self):
        plan_path = self.root / "cli-plan.json"
        create = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "pipeline.py"),
                "plan",
                "--source",
                str(self.source),
                "--output",
                str(self.output),
                "--out",
                str(plan_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(create.returncode, 0, create.stderr)
        draft = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(draft, self.plan())

        draft["edits"] = self.peq_plan()["edits"]
        plan_path.write_text(json.dumps(draft), encoding="utf-8")
        apply = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "pipeline.py"),
                "apply",
                "--plan",
                str(plan_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(apply.returncode, 0, apply.stderr)
        manifest = json.loads(apply.stdout)
        self.assertTrue(manifest["verification"]["roundtrip_lint"]["pass"])
        self.assertTrue(self.output.is_file())

    def test_apply_plan_verifies_confirmed_delay_and_output_trim(self):
        plan = self.plan()
        plan["edits"] = [
            {
                "id": "delay-1",
                "kind": "delay_samples",
                "channel": 0,
                "samples": 96,
            },
            {
                "id": "trim-1",
                "kind": "output_trim",
                "channel": 0,
                "trim_db": -1.5,
            },
        ]
        plan["confirmations"] = {"delay-1": True, "trim-1": True}
        plan_path = self.root / "protected-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")

        manifest = pipeline.apply_plan(plan_path)

        output_xml = afpx.decode(self.output)
        self.assertEqual(afpx.attrs(afpx.delay_tags(output_xml)[0])["T"], "96")
        self.assertAlmostEqual(afpx.read_output_levels(output_xml)[0]["db"], -1.5, places=6)
        self.assertEqual(
            [entry["kind"] for entry in manifest["verification"]["edits"]],
            ["delay_samples", "output_trim"],
        )
        self.assertTrue(all(
            entry["result"]["pass"] for entry in manifest["verification"]["edits"]
        ))
        self.assertTrue(manifest["verification"]["roundtrip_lint"]["pass"])
        self.assertEqual(manifest["verification"]["roundtrip_lint"]["slots_changed"], 0)


if __name__ == "__main__":
    unittest.main()
