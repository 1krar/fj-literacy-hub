import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import windows_diagnostics as diagnostics
import start_assistant
import install_assistant

class PortableLauncherTests(unittest.TestCase):
    def test_missing_files_and_foreign_port_are_actionable(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(diagnostics,'local_json',side_effect=OSError), patch.object(diagnostics.socket,'socket') as socket:
            socket.return_value.__enter__.return_value.connect_ex.return_value=0
            rows=diagnostics.diagnose(Path(folder))
            self.assertTrue(any(r['name']=='运行包文件' and r['state']=='失败' for r in rows))
            self.assertTrue(any('其他程序占用' in r['detail'] for r in rows))

    def test_report_does_not_include_credential_fields(self):
        rows=[{'name':'书生 API','state':'通过','detail':'已配置模型','api_key':'fixture-secret','question':'private question'}]
        value=diagnostics.report(rows)
        self.assertNotIn('fixture-secret',value);self.assertNotIn('private question',value)

    def test_frozen_protocol_uses_executable_not_python_script(self):
        with patch.object(install_assistant.sys,'frozen',True,create=True), patch.object(install_assistant,'ensure_environment'), patch.object(install_assistant.sys,'executable','C:/portable/CTRLHelper.exe'), patch.object(Path,'is_file',return_value=True), patch.object(install_assistant.winreg,'CreateKey'),patch.object(install_assistant.winreg,'SetValueEx') as write,patch.object(install_assistant.sys,'argv',['installer']):
            install_assistant.main()
        command=write.call_args.args[4]
        self.assertIn('--launch --protocol',command);self.assertNotIn('pythonw.exe',command)

    def test_frozen_missing_playwright_never_spawns_pip(self):
        with patch.object(start_assistant.sys,'frozen',True,create=True),patch.object(start_assistant.importlib.util,'find_spec',return_value=None),patch.object(start_assistant.subprocess,'run') as run:
            with self.assertRaisesRegex(RuntimeError,'运行包缺少'):start_assistant.ensure_environment()
            run.assert_not_called()

if __name__=='__main__':unittest.main()
