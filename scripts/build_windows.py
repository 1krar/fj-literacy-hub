"""Build a Windows x64 portable folder; include public assets only."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output'

def main():
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed',
             '--name','CTRLHelper','--distpath',str(OUT/'windows'),'--workpath',str(OUT/'pyinstaller'),
             '--specpath',str(OUT),'--paths',str(ROOT/'scripts'),
             '--paths',str(ROOT/'vendor/evidence-chain/src'),'--collect-all','playwright',
             '--hidden-import','playwright.sync_api','--hidden-import','playwright.async_api',
             '--hidden-import','evidence_chain.providers.ai.gemini_web',
             '--hidden-import','evidence_chain.providers.ai.deepseek_web',
             str(ROOT/'scripts/windows_launcher.py')]
    subprocess.run(command,check=True,cwd=ROOT)
    package=OUT/'windows/CTRLHelper'
    shutil.copytree(ROOT/'dist',package/'dist',dirs_exist_ok=True)
    # Copy only public Python provider sources, never profiles or .runtime.
    source=ROOT/'vendor/evidence-chain/src'
    for file in source.rglob('*.py'):
        target=package/'vendor/evidence-chain/src'/file.relative_to(source)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(file,target)
    shutil.copyfile(ROOT/'docs/windows-portable.md',package/'使用说明.md')
    archive=ROOT.parent/'output/sites/ctrl-assistant-windows-x64.zip'
    archive.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
        for file in package.rglob('*'):
            relative=file.relative_to(package)
            if not file.is_file() or any(part in ('.runtime','__pycache__','.git') for part in relative.parts):continue
            tcl_encoding = relative.parts[:3] == ('_internal', '_tcl_data', 'encoding')
            if file.suffix == '.dpapi' or (file.suffix == '.enc' and not tcl_encoding):
                raise RuntimeError('Private credential file detected: '+relative.as_posix())
            bundle.write(file,'CTRLHelper/'+relative.as_posix())
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size},ensure_ascii=False))

if __name__=='__main__':main()
