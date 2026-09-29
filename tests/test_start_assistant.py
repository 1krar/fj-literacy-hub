import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch

spec=importlib.util.spec_from_file_location('start_assistant',Path(__file__).resolve().parents[1]/'scripts/start_assistant.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class LauncherTests(unittest.TestCase):
    def test_protocol_only_accepts_fixed_open_action(self):
        for url in ('literacy-assistant://open','literacy-assistant://open/'):
            module.validate_protocol(url)
        for url in ('https://example.com','literacy-assistant://open?cmd=anything','literacy-assistant://open#args','literacy-assistant://other','literacy-assistant://open/path','literacy-assistant://open" --no-browser'):
            with self.assertRaises(ValueError):module.validate_protocol(url)

    def test_running_checks_app_identity(self):
        with patch.object(module,'build_opener') as opener:
            response=opener.return_value.open.return_value.__enter__.return_value
            response.headers.get.return_value='other'
            self.assertFalse(module.running())
            response.headers.get.return_value='1'
            self.assertTrue(module.running())

    def test_warm_start_does_not_install_or_spawn_service(self):
        with patch.object(module,'running',return_value=True),patch.object(module,'startup_lock'),patch.object(module,'ensure_environment') as setup,patch.object(module.subprocess,'Popen') as spawn,patch.object(module.sys,'argv',['launcher','--no-browser','--protocol','literacy-assistant://open']):
            module.main()
            setup.assert_not_called();spawn.assert_not_called()

    def test_cold_start_checks_environment_and_waits_before_opening(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.runtime').mkdir()
            with patch.object(module,'ROOT',root),patch.object(module,'running',side_effect=[False,True]),patch.object(module,'startup_lock'),patch.object(module,'ensure_environment') as setup,patch.object(module.subprocess,'Popen') as spawn,patch.object(module,'open_edge') as edge,patch.object(module.sys,'argv',['launcher']):
                spawn.return_value.pid=123
                module.main()
                setup.assert_called_once();edge.assert_called_once_with(module.URL)
                self.assertEqual((root/'.runtime/assistant.pid').read_text(),'123')
                self.assertIn(str(root/'scripts/assistant_server.py'),spawn.call_args.args[0])

    def test_web_protocol_does_not_open_duplicate_assistant_tab(self):
        with patch.object(module,'running',return_value=True),patch.object(module,'startup_lock'),patch.object(module,'open_edge') as edge,patch.object(module.sys,'argv',['launcher','--protocol','literacy-assistant://open']):
            module.main()
            edge.assert_not_called()

if __name__=='__main__':unittest.main()
