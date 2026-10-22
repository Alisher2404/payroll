"""Упаковка исходников без окружения, рабочих данных и кэшей."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from fnmatch import fnmatch

root=Path(__file__).resolve().parent
target=root.parent/'payroll-release.zip'
with ZipFile(target,'w',ZIP_DEFLATED) as archive:
    for path in root.rglob('*'):
        relative=path.relative_to(root)
        if any(part.startswith('.venv') or part in {'.git','__pycache__','.pytest_cache','data','backups','qa','secrets','private'} for part in relative.parts):
            continue
        if path.name in {'secrets.toml','.env'} or path.name.startswith(('.env.','credentials','passwords')) or path.suffix in {'.db','.sqlite','.sqlite3','.log','.bak','.backup','.pem','.key','.zip'}:
            continue
        if any(fnmatch(path.name,pattern) for pattern in ['*.db-*','*.db3*','*.sqlite-*','*.sqlite3-*','*.dump','id_rsa*','id_ed25519*']):
            continue
        if fnmatch(path.name,'*secrets*.toml') and path.name!='secrets.example.toml':
            continue
        if path.is_file():
            archive.write(path,Path('payroll')/relative)
print(target)
