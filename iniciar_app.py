
"""Inicializador clicável do Equalizador de Propostas no Windows."""

from __future__ import annotations

import os
import hashlib
import json
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
PYTHON = VENV / "Scripts" / "python.exe"
URL = "http://127.0.0.1:8000"
PID_FILE = ROOT / ".equalizador.pid"
DEPENDENCY_MARKER = VENV / ".dependencies-installed"


def assinatura_aplicacao() -> str:
    digest = hashlib.sha256()
    files = [ROOT / "app.py", ROOT / "iniciar_app.py"]
    files.extend(sorted((ROOT / "web").glob("*")))
    files.extend(sorted((ROOT / "src" / "equalizador").glob("*.py")))
    for path in files:
        if path.is_file():
            stat = path.stat()
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
    return digest.hexdigest()[:16]


def servidor_disponivel(build: str | None = None) -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/health", timeout=1) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return (
                payload.get("service") == "equalizador"
                and (build is None or payload.get("build") == build)
            )
    except (OSError, urllib.error.URLError):
        return False


def preparar_ambiente() -> None:
    if not PYTHON.exists():
        print("Criando ambiente virtual .venv...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    requirements = ROOT / "requirements.txt"
    if not DEPENDENCY_MARKER.exists() or requirements.stat().st_mtime > DEPENDENCY_MARKER.stat().st_mtime:
        print("Atualizando dependencias...")
        subprocess.check_call(
            [str(PYTHON), "-m", "pip", "install", "-r", str(requirements)],
            cwd=ROOT,
        )
        DEPENDENCY_MARKER.touch()
    else:
        print("Dependencias ja estao atualizadas.")


def encerrar_processo_anterior() -> None:
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
        listener_pids = _listener_pids()
        if str(pid) in listener_pids and servidor_disponivel():
            os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if not servidor_disponivel():
                break
            time.sleep(0.25)
    except (OSError, ValueError):
        pass
    finally:
        PID_FILE.unlink(missing_ok=True)


def encerrar_listener_da_porta() -> None:
    """Libera a porta oficial quando uma execução manual ficou sem PID."""
    if os.name != "nt":
        return
    if not servidor_disponivel():
        return
    for pid in _listener_pids():
        if pid == str(os.getpid()):
            continue
        subprocess.run(
            ["taskkill", "/PID", pid, "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )

    for _ in range(20):
        if not porta_ocupada():
            return
        time.sleep(0.25)


def _listener_pids() -> set[str]:
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return set()

    pids = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0].upper() == "TCP":
            address, state, pid = fields[1], fields[3].upper(), fields[4]
            if address.endswith(":8000") and state == "LISTENING" and pid.isdigit():
                pids.add(pid)
    return pids


def porta_ocupada() -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=0.3):
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, urllib.error.URLError):
        return False


def aguardar_servidor(process: subprocess.Popen, build: str) -> None:
    for _ in range(120):
        if servidor_disponivel(build):
            webbrowser.open(f"{URL}/?build={build}")
            print(f"Aplicacao aberta em {URL}")
            return
        if process.poll() is not None:
            raise RuntimeError("O servidor encerrou antes de ficar disponivel.")
        time.sleep(0.5)
    process.terminate()
    raise TimeoutError("O servidor demorou mais de 60 segundos para iniciar.")


def main() -> None:
    os.chdir(ROOT)
    build = assinatura_aplicacao()
    if servidor_disponivel(build):
        webbrowser.open(f"{URL}/?build={build}")
        print(f"Aplicacao ja estava em execucao: {URL}")
        return

    encerrar_processo_anterior()
    if porta_ocupada() and servidor_disponivel():
        encerrar_listener_da_porta()
    if porta_ocupada():
        raise RuntimeError("A porta 8000 esta ocupada por outro processo. Feche-o e tente novamente.")
    preparar_ambiente()
    environment = os.environ.copy()
    environment["EQUALIZADOR_BUILD"] = build
    process = subprocess.Popen(
        [str(PYTHON), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
        env=environment,
    )
    PID_FILE.write_text(str(process.pid), encoding="ascii")
    try:
        aguardar_servidor(process, build)
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
    except Exception:
        process.terminate()
        raise
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Erro ao iniciar o Equalizador: {exc}")
        input("Pressione Enter para fechar...")