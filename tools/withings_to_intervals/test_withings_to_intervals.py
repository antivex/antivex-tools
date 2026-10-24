import contextlib
import io
import os
import tempfile
import unittest
import zipfile

import withings_to_intervals as w

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.join(HERE, "samples")


def load(*names):
    return w.load_export([os.path.join(S, n) for n in names])


class ReadTests(unittest.TestCase):
    def test_last_measurement_of_the_day_wins(self):
        days = w.read_weight(load("weight.csv")[0])
        self.assertEqual(days["2026-10-01"]["weight"], 80.6)
        self.assertEqual(sorted(days), ["2026-10-01", "2026-10-02", "2026-10-03"])

    def test_body_fat_percent_from_mass(self):
        days = w.read_weight(load("weight.csv")[0])
        self.assertAlmostEqual(days["2026-10-01"]["fat_pct"], 16.1 / 80.6 * 100)
        self.assertIsNone(days["2026-10-02"]["fat_pct"])

    def test_pounds_are_converted(self):
        days = w.read_weight(load("weight_lb.csv")[0])
        self.assertAlmostEqual(days["2026-10-01"]["weight"], 80.0, places=1)
        self.assertAlmostEqual(days["2026-10-01"]["fat_pct"], 35.3 / 176.4 * 100)

    def test_blood_pressure_last_of_day(self):
        days = w.read_bp(load("bp.csv")[1])
        self.assertEqual(days["2026-10-02"]["systolic"], 130)
        self.assertEqual(days["2026-10-02"]["hr"], 80)

    def test_zip_and_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "export.zip")
            with zipfile.ZipFile(path, "w") as archive:
                archive.write(os.path.join(S, "weight.csv"), "weight.csv")
                archive.write(os.path.join(S, "bp.csv"), "bp.csv")
            weight_rows, bp_rows = w.load_export([path])
            self.assertTrue(weight_rows and bp_rows)
        weight_rows, bp_rows = w.load_export([S])
        self.assertTrue(weight_rows and bp_rows)

    def test_unknown_columns_give_nothing(self):
        self.assertEqual(w.read_weight([{"foo": "1"}]), {})
        self.assertEqual(w.read_bp([{"foo": "1"}]), {})

    def test_column_names_case_and_bom(self):
        rows = [{"﻿DATE": "2026-10-05 08:00:00", "WEIGHT (KG)": "70,5"}]
        self.assertEqual(w.read_weight(rows)["2026-10-05"]["weight"], 70.5)


class MappingTests(unittest.TestCase):
    def records(self, since=None):
        weight_rows, bp_rows = load("weight.csv", "bp.csv")
        return w.merge(w.read_weight(weight_rows), w.read_bp(bp_rows), since)

    def test_merge_and_since(self):
        self.assertEqual([r["date"] for r in self.records()], ["2026-10-01", "2026-10-02", "2026-10-03"])
        self.assertEqual([r["date"] for r in self.records("2026-10-02")], ["2026-10-02", "2026-10-03"])

    def test_wellness_body(self):
        body = w.to_wellness(self.records())
        self.assertEqual(body[0], {"id": "2026-10-01", "weight": 80.6, "bodyFat": 20.0, "systolic": 118, "diastolic": 76})
        self.assertNotIn("restingHR", body[0])
        self.assertEqual(body[2], {"id": "2026-10-03", "weight": 79.5, "bodyFat": 20.0})

    def test_send_chunks_without_network(self):
        sent = []
        body = [{"id": f"d{i}", "weight": 1} for i in range(250)]
        n = w.send_wellness(body, "i1", "KEY", put=lambda url, chunk, key: sent.append((url, len(chunk), key)))
        self.assertEqual(n, 3)
        self.assertEqual([s[1] for s in sent], [100, 100, 50])
        self.assertEqual(sent[0][0], "https://intervals.icu/api/v1/athlete/i1/wellness-bulk")


class CliTests(unittest.TestCase):
    def run_main(self, argv, put=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = w.main(argv, put=put)
        return code, out.getvalue(), err.getvalue()

    def test_default_is_dry_run(self):
        calls = []
        code, out, _ = self.run_main([os.path.join(S, "weight.csv")], put=lambda *a: calls.append(a))
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])
        self.assertIn("Nothing was sent", out)
        self.assertIn("80.6", out)

    def test_send_needs_credentials(self):
        os.environ.pop("INTERVALS_API_KEY", None)
        code, _, err = self.run_main([os.path.join(S, "weight.csv"), "--send"])
        self.assertEqual(code, 2)
        self.assertIn("--athlete-id", err)

    def test_send_uses_env_key_and_hides_it(self):
        calls = []
        os.environ["INTERVALS_API_KEY"] = "SECRET"
        try:
            code, out, err = self.run_main(
                [os.path.join(S, "weight.csv"), "--send", "--athlete-id", "i9"], put=lambda *a: calls.append(a)
            )
        finally:
            del os.environ["INTERVALS_API_KEY"]
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2], "SECRET")
        self.assertNotIn("SECRET", out + err)

    def test_out_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "clean.csv")
            code, _, _ = self.run_main([os.path.join(S, "weight.csv"), os.path.join(S, "bp.csv"), "--out", path])
            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        self.assertEqual(lines[0], "data,peso_kg,grasso_pct,sistolica,diastolica,battito")
        self.assertEqual(lines[1], "2026-10-01,80.6,20.0,118,76,62")

    def test_empty_export_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_main([tmp])
        self.assertEqual(code, 1)
        self.assertIn("No weight", err)


if __name__ == "__main__":
    unittest.main()
