"""Synthetic file isolation tests; no sample dataset/model/provider required."""
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('generalization', pathlib.Path(__file__).parents[1] / 'qa/generalization.py')
generalization = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generalization)

class WorkspaceTests(unittest.TestCase):
    def test_shift_preserves_nonmatching_ids(self):
        self.assertEqual(generalization.shift('WELL-0001 INS-0002 U-104 WELL-1000'), 'WELL-9001 INS-9002 U-9104 WELL-1000')

    def test_transform_copies_shifted_names_text_and_binary_without_changing_source(self):
        with tempfile.TemporaryDirectory() as root:
            src=pathlib.Path(root)/'source';src.mkdir();(src/'WELL-0001').mkdir()
            (src/'WELL-0001'/'INS-0002.md').write_text('WELL-0001 U-104')
            (src/'binary.bin').write_bytes(b'\xff\xfe\x00')
            dst=pathlib.Path(root)/'output'
            generalization.transform(str(src),str(dst))
            self.assertEqual((dst/'WELL-9001'/'INS-9002.md').read_text(),'WELL-9001 U-9104')
            self.assertEqual((dst/'binary.bin').read_bytes(),b'\xff\xfe\x00')
            self.assertEqual((src/'WELL-0001'/'INS-0002.md').read_text(),'WELL-0001 U-104')

    def test_missing_source_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as root:
            dst=pathlib.Path(root)/'output'
            with self.assertRaises(FileNotFoundError):generalization.transform(str(pathlib.Path(root)/'missing'),str(dst))
            self.assertFalse(dst.exists())

    def test_existing_destination_is_never_removed(self):
        with tempfile.TemporaryDirectory() as root:
            src=pathlib.Path(root)/'source';src.mkdir();dst=pathlib.Path(root)/'output';dst.mkdir();sentinel=dst/'keep';sentinel.write_text('keep')
            with self.assertRaises(FileExistsError):generalization.transform(str(src),str(dst))
            self.assertEqual(sentinel.read_text(),'keep')

    def run_probe(self, source, seen, fail=False):
        def ingest(dst,db):
            seen.append((dst,db));self.assertTrue(pathlib.Path(dst).is_dir());pathlib.Path(db).write_text('synthetic')
        def probes(db):
            self.assertTrue(pathlib.Path(db).exists())
            if fail:raise RuntimeError('synthetic failure')
            return 1
        with patch.object(generalization,'ingest',side_effect=ingest),patch.object(generalization,'probes',side_effect=probes):
            return generalization.main([str(source)])

    def test_runs_have_distinct_temporary_paths_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            src=pathlib.Path(root)/'source';src.mkdir();seen=[]
            self.assertEqual(self.run_probe(src,seen),1);self.assertEqual(self.run_probe(src,seen),1)
            self.assertNotEqual(seen[0],seen[1])
            for dst,db in seen:self.assertFalse(pathlib.Path(dst).exists());self.assertFalse(pathlib.Path(db).exists())

    def test_failure_also_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as root:
            src=pathlib.Path(root)/'source';src.mkdir();seen=[]
            with self.assertRaises(RuntimeError):self.run_probe(src,seen,fail=True)
            self.assertFalse(pathlib.Path(seen[0][0]).exists());self.assertFalse(pathlib.Path(seen[0][1]).exists())

    def test_nested_destination_rejected_before_copying(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):generalization.transform(root,str(pathlib.Path(root)/'nested'))
            self.assertFalse((pathlib.Path(root)/'nested').exists())
