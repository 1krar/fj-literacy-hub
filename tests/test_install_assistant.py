from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import install_assistant as installer


class StartupRegistrationTests(unittest.TestCase):
    def test_login_startup_runs_only_this_helper_without_opening_browser(self):
        with patch.object(installer.winreg, 'CreateKey') as create, patch.object(installer.winreg, 'SetValueEx') as set_value:
            installer.set_startup(True, Path('C:/Python312/pythonw.exe'))
        create.assert_called_once_with(installer.winreg.HKEY_CURRENT_USER, installer.STARTUP_KEY)
        command = set_value.call_args.args[4]
        self.assertIn('scripts\\start_assistant.py', command)
        self.assertTrue(command.endswith(' --no-browser'))
        self.assertNotIn('--protocol', command)

    def test_disabling_removes_only_our_login_entry(self):
        with patch.object(installer.winreg, 'OpenKey'), patch.object(installer.winreg, 'QueryValueEx', return_value=('"C:\\Python312\\pythonw.exe" -B "D:\\literacy-hub\\scripts\\start_assistant.py" --no-browser', installer.winreg.REG_SZ)), patch.object(installer.winreg, 'DeleteValue') as delete:
            installer.set_startup(False, Path('C:/Python312/pythonw.exe'))
            delete.assert_called_once()
        with patch.object(installer.winreg, 'OpenKey'), patch.object(installer.winreg, 'QueryValueEx', return_value=('other-app.exe', installer.winreg.REG_SZ)), patch.object(installer.winreg, 'DeleteValue') as delete:
            installer.set_startup(False, Path('C:/Python312/pythonw.exe'))
            delete.assert_not_called()


if __name__ == '__main__': unittest.main()
