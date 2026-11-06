import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('gpu_process_details',Path(__file__).resolve().parents[1]/'scripts/gpu-selector/process_details.py')
details=importlib.util.module_from_spec(spec);spec.loader.exec_module(details)


class ProcessDetailsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'77').mkdir()

    def test_original_executable_and_owner_replace_renamed_display(self):
        with patch.object(details.os,'readlink',return_value='/home/user/env/bin/python'):
            value=details.process_details(77,'python455',self.root,lambda uid:'researcher')
        self.assertEqual(value['user'],'researcher')
        self.assertEqual(value['name'],'/home/user/env/bin/python')

    def test_foreign_process_keeps_driver_name_when_exe_is_private(self):
        with patch.object(details.os,'readlink',side_effect=PermissionError):
            value=details.process_details(77,'/home/example/env/bin/python',self.root,lambda uid:'other-user')
        self.assertEqual(value['user'],'other-user')
        self.assertEqual(value['name'],'/home/example/env/bin/python')

    def test_exited_process_is_unknown_instead_of_wrong_owner(self):
        with patch.object(details.os,'readlink',side_effect=FileNotFoundError):
            value=details.process_details(88,'original',self.root,lambda uid:'wrong-user')
        self.assertEqual(value,{'name':'original','user':'未知'})

    def test_unmapped_uid_still_has_numeric_identity(self):
        with patch.object(details.os,'readlink',side_effect=PermissionError):
            def missing(uid):raise KeyError(uid)
            value=details.process_details(77,'original',self.root,missing)
        self.assertEqual(value['user'],'UID '+str(value['uid']))
