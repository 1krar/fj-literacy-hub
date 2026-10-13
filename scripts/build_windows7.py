"""API-only Win7 trial: official embedded Python; no system installation."""
from pathlib import Path
import hashlib
import json
import shutil
from urllib.request import urlopen
import zipfile

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=('app_paths.py','api_only.py','assistant_server.py','start_assistant.py',
         'windows7_launcher.py','windows_diagnostics.py','ctrl_assistant.py',
         'ctrl_multi.py','ctrl_dispatch.py','ctrl_review.py','qwen_api.py','intern_api.py')
RUNTIMES={'x64':('amd64','3acb1d7d9bde5a79f840167b166bb633'),
          'x86':('win32','659adf421e90fba0f56a9631f79e70fb')}

def main():
    output=ROOT/'output/windows7';output.mkdir(parents=True,exist_ok=True)
    artifacts=[]
    for arch,(runtime_arch,expected) in RUNTIMES.items():
        url='https://www.python.org/ftp/python/3.8.10/python-3.8.10-embed-'+runtime_arch+'.zip'
        downloaded=output/('python-'+arch+'.zip')
        if not downloaded.is_file():
            with urlopen(url,timeout=60) as response:raw=response.read()
            if hashlib.md5(raw).hexdigest()!=expected:raise RuntimeError('Official runtime checksum mismatch')
            downloaded.write_bytes(raw)
        raw=downloaded.read_bytes()
        if hashlib.md5(raw).hexdigest()!=expected:raise RuntimeError('Cached runtime checksum mismatch')
        package=output/('CTRL-Win7-API-'+arch)
        runtime=package/'runtime';runtime.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(downloaded) as source:
            for name in source.namelist():
                if name.startswith(('/', '\\')) or '..' in Path(name).parts:raise RuntimeError('Unsafe runtime archive')
            source.extractall(runtime)
        # Isolated embedded distribution: explicit, local code paths only.
        (runtime/'python38._pth').write_text('python38.zip\n.\n../scripts\n../\n',encoding='ascii')
        scripts=package/'scripts';scripts.mkdir(exist_ok=True)
        for name in SCRIPTS:shutil.copyfile(ROOT/'scripts'/name,scripts/name)
        shutil.copytree(ROOT/'dist',package/'dist',dirs_exist_ok=True)
        (package/'api-only.json').write_text(json.dumps({'api_only':True,'trial':True,'python':'3.8.10','arch':arch}),encoding='utf-8')
        (package/'build-info.json').write_text(json.dumps({'runtime_url':url,'runtime_sha256':hashlib.sha256(raw).hexdigest(),
            'tested_platform':'Windows 11; Windows 7 real device validation pending'},indent=2),encoding='utf-8')
        for name,argument in [('启动 CTRL 助手.cmd',''),('启动诊断.cmd',' --diagnose')]:
            content='@echo off\r\n"%~dp0runtime\\python.exe" -X utf8 -B "%~dp0scripts\\windows7_launcher.py"'+argument+'\r\nif errorlevel 1 pause\r\n'
            (package/name).write_bytes(content.encode('ascii'))
        shutil.copyfile(ROOT/'docs/windows7-api.md',package/'使用说明.md')
        archive=ROOT.parent/'output/sites'/('ctrl-assistant-win7-api-'+arch+'.zip')
        archive.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as bundle:
            for file in package.rglob('*'):
                rel=file.relative_to(package)
                if not file.is_file() or any(part in ('.runtime','__pycache__','.git') for part in rel.parts):continue
                if file.suffix in ('.dpapi','.enc'):raise RuntimeError('Private file in API package')
                bundle.write(file,package.name+'/'+rel.as_posix())
        artifacts.append({'archive':str(archive),'bytes':archive.stat().st_size})
    print(json.dumps(artifacts,ensure_ascii=False))

if __name__=='__main__':main()
