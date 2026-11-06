"""Restrição de permissões de arquivos e diretórios locais.

POSIX usa ``chmod`` (0700 para diretórios, 0600 para arquivos). No Windows,
onde ``chmod`` não representa ACL, usamos ``icacls`` para remover a herança e
conceder acesso apenas ao usuário atual. Falhas são tratadas como best effort:
o chamador recebe ``False`` e a CLI continua funcionando, mas os testes de
segurança verificam que a restrição realmente foi aplicada.
"""

from __future__ import annotations

import getpass
import os
import shutil

# Executa o icacls com lista fixa de argumentos e sem shell.
import subprocess  # nosec B404
from pathlib import Path


def current_principal() -> str:
    """Nome da conta atual no formato aceito por ``icacls``."""
    user = os.environ.get("USERNAME") or getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    if domain and "\\" not in user:
        return f"{domain}\\{user}"
    return user


def restrict_path(path: Path, *, directory: bool) -> bool:
    """Aplica a permissão mais restritiva possível para o tipo de caminho."""
    target = Path(path)
    try:
        if os.name == "nt":
            return _restrict_windows(target, directory=directory)
        target.chmod(0o700 if directory else 0o600)
        return True
    except OSError:
        return False


def _restrict_windows(path: Path, *, directory: bool) -> bool:
    principal = current_principal()
    if not principal or any(char in principal for char in '\r\n"'):
        return False
    executable = shutil.which("icacls")
    if executable is None:
        return False

    grant = f"{principal}:(OI)(CI)F" if directory else f"{principal}:F"
    command = [executable, str(path), "/inheritance:r", "/grant:r", grant]
    try:
        # Lista fixa de argumentos, sem shell e com executável resolvido.
        result = subprocess.run(  # nosec B603
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
