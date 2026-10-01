# -*- coding: utf-8 -*-
"""Verificação, download e instalação de novas versões publicadas no GitHub.

Os instaladores (Inno Setup) são gerados e publicados localmente
(publish_release.ps1) como assets dos releases de UPDATE_REPO,
junto com um arquivo .sha256 de cada um.
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                             QMessageBox, QProgressBar, QPushButton,
                             QTextBrowser, QVBoxLayout)

from libs.__init__ import __version__ as APP_VERSION

# Repositório público onde os instaladores são publicados (publish_release.ps1).
UPDATE_REPO = 'FialhoTKL/labelImg-master'

API_LATEST_RELEASE = 'https://api.github.com/repos/%s/releases/latest' % UPDATE_REPO
INSTALLER_PATTERN = re.compile(r'^LabelImg_Setup_.*\.exe$', re.IGNORECASE)
HEADERS = {
    'Accept': 'application/vnd.github+json',
    'User-Agent': 'LabelImg/%s' % APP_VERSION,
}

FROZEN = getattr(sys, 'frozen', False)


class UpdateError(Exception):
    """Falha ao consultar, baixar ou validar uma atualização."""


def version_tuple(version):
    """'v1.10.2' -> (1, 10, 2). Partes não numéricas são ignoradas."""
    numbers = re.findall(r'\d+', version or '')
    return tuple(int(n) for n in numbers[:3]) or (0,)


def is_newer(candidate, current=APP_VERSION):
    return version_tuple(candidate) > version_tuple(current)


def _network_error(exc, what):
    if isinstance(exc, urllib.error.HTTPError):
        return 'Erro HTTP %s em %s.' % (exc.code, what)
    reason = getattr(exc, 'reason', exc)
    return 'Sem conexão com o GitHub (%s): %s' % (what, reason)


def _open(url, timeout):
    request = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(request, timeout=timeout)


def check_for_update(current=APP_VERSION, timeout=5):
    """Consulta o último release publicado.

    Retorna um dict com os dados da atualização se houver versão mais nova com
    instalador anexado; None se já estiver atualizado. Levanta UpdateError em
    falha de rede/servidor (quem chama decide se mostra).
    """
    try:
        with _open(API_LATEST_RELEASE, timeout) as resp:
            release = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Repositório sem nenhum release publicado ainda.
            return None
        raise UpdateError(_network_error(e, 'verificação de atualização'))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(_network_error(e, 'verificação de atualização'))

    tag = release.get('tag_name', '')
    if release.get('draft') or release.get('prerelease') or not is_newer(tag, current):
        return None

    assets = release.get('assets', [])
    installer = next((a for a in assets if INSTALLER_PATTERN.match(a.get('name', ''))), None)
    if not installer:
        return None

    sha_name = installer['name'].lower() + '.sha256'
    sha = next((a for a in assets if a.get('name', '').lower() == sha_name), None)

    return {
        'version': tag.lstrip('vV'),
        'notes': release.get('body') or '',
        'page': release.get('html_url', ''),
        'installer_name': installer['name'],
        'installer_url': installer['browser_download_url'],
        'size': installer.get('size', 0),
        'sha256_url': sha['browser_download_url'] if sha else None,
    }


def _expected_sha256(url):
    try:
        with _open(url, 15) as resp:
            text = resp.read().decode('ascii', errors='replace')
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError(_network_error(e, 'checksum do instalador'))
    # Formato "hash  nome_do_arquivo" ou só "hash".
    parts = text.strip().split()
    if not parts or not re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]):
        raise UpdateError('Arquivo de checksum do instalador inválido.')
    return parts[0].lower()


def _remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def download_installer(info, progress_callback=None, dest_dir=None):
    """Baixa o instalador, confere tamanho e SHA-256 e devolve o caminho.

    progress_callback recebe um inteiro de 0 a 100.
    """
    if not info.get('sha256_url'):
        raise UpdateError('Release sem arquivo de checksum (.sha256); atualização cancelada por segurança.')

    path = os.path.join(dest_dir or tempfile.gettempdir(), info['installer_name'])
    downloaded = 0
    sha = hashlib.sha256()

    try:
        expected = _expected_sha256(info['sha256_url'])
        with _open(info['installer_url'], 60) as resp, open(path, 'wb') as f:
            total = int(resp.headers.get('Content-Length') or info.get('size') or 0)
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                sha.update(chunk)
                downloaded += len(chunk)
                if progress_callback and total:
                    progress_callback(min(100, int(downloaded * 100 / total)))
    except UpdateError:
        _remove(path)
        raise
    except urllib.error.URLError as e:
        _remove(path)
        raise UpdateError(_network_error(e, 'download do instalador'))
    except OSError as e:
        _remove(path)
        raise UpdateError('Erro ao baixar/gravar o instalador: %s' % e)

    if info.get('size') and downloaded != info['size']:
        _remove(path)
        raise UpdateError('Download do instalador incompleto. Tente novamente.')
    if sha.hexdigest() != expected:
        _remove(path)
        raise UpdateError('O instalador baixado não confere com o checksum publicado. Atualização cancelada.')
    return path


def run_installer(path):
    """Inicia o instalador em modo silencioso, desacoplado deste processo.

    O app deve encerrar logo em seguida; o instalador substitui os arquivos e
    reabre o programa ao terminar.
    """
    flags = 0
    if os.name == 'nt':
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [path, '/SILENT', '/SP-', '/NOCANCEL', '/CLOSEAPPLICATIONS', '/NORESTART'],
        creationflags=flags,
        close_fds=True,
    )


class CheckUpdateWorker(QThread):
    """Consulta o GitHub sem travar a interface."""
    update_available = pyqtSignal(dict)
    up_to_date = pyqtSignal()
    error = pyqtSignal(str)

    def run(self):
        try:
            info = check_for_update()
        except UpdateError as e:
            self.error.emit(str(e))
            return
        except Exception as e:
            self.error.emit('Erro inesperado ao verificar atualização: %s' % e)
            return
        if info:
            self.update_available.emit(info)
        else:
            self.up_to_date.emit()


class DownloadUpdateWorker(QThread):
    """Baixa e valida o instalador da nova versão."""
    progress = pyqtSignal(int)
    finished_ok = pyqtSignal(str)  # caminho do instalador
    error = pyqtSignal(str)

    def __init__(self, info):
        super(DownloadUpdateWorker, self).__init__()
        self.info = info

    def run(self):
        try:
            path = download_installer(self.info, self.progress.emit)
        except UpdateError as e:
            self.error.emit(str(e))
            return
        except Exception as e:
            self.error.emit('Erro inesperado ao baixar a atualização: %s' % e)
            return
        self.finished_ok.emit(path)


class UpdateDialog(QDialog):
    """Oferece a nova versão, baixa o instalador e o executa."""

    def __init__(self, info, on_ignore=None, parent=None):
        super(UpdateDialog, self).__init__(parent)
        self.info = info
        self.on_ignore = on_ignore
        self.worker = None
        self.setWindowTitle('Atualização disponível')
        self.setMinimumSize(520, 380)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>Nova versão disponível: %s</b><br>Versão instalada: %s'
                                % (info['version'], APP_VERSION)))
        layout.addWidget(QLabel('Novidades:'))
        notes = QTextBrowser()
        notes.setOpenExternalLinks(True)
        notes.setMarkdown(info.get('notes') or '_Sem notas para esta versão._')
        layout.addWidget(notes)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setOpenExternalLinks(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.button_ignore = QPushButton('Ignorar esta versão')
        self.button_ignore.clicked.connect(self.ignore_version)
        buttons.addWidget(self.button_ignore)
        buttons.addStretch()
        self.button_later = QPushButton('Lembrar depois')
        self.button_later.clicked.connect(self.reject)
        buttons.addWidget(self.button_later)
        self.button_update = QPushButton('Atualizar agora')
        self.button_update.setDefault(True)
        self.button_update.clicked.connect(self.start_download)
        buttons.addWidget(self.button_update)
        layout.addLayout(buttons)

    def ignore_version(self):
        if self.on_ignore:
            self.on_ignore(self.info['version'])
        self.reject()

    def _set_buttons_enabled(self, enabled):
        for button in (self.button_ignore, self.button_later, self.button_update):
            button.setEnabled(enabled)

    def start_download(self):
        self._set_buttons_enabled(False)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.status.setText('Baixando a nova versão...')

        self.worker = DownloadUpdateWorker(self.info)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished_ok.connect(self.install)
        self.worker.error.connect(self.download_failed)
        self.worker.start()

    def download_failed(self, message):
        logging.warning('Falha no download da atualização: %s', message)
        self.progress.setVisible(False)
        page = self.info.get('page', '')
        self.status.setText('%s<br>Você pode tentar novamente ou baixar manualmente em:<br>'
                            '<a href="%s">%s</a>' % (message, page, page))
        self._set_buttons_enabled(True)
        self.button_update.setText('Tentar novamente')

    def install(self, path):
        self.status.setText('Instalando... o programa será reaberto ao terminar.')
        try:
            run_installer(path)
        except OSError as e:
            QMessageBox.critical(self, 'Erro', 'Não foi possível iniciar o instalador: %s' % e)
            self._set_buttons_enabled(True)
            return
        # Fecha o app para o instalador poder substituir os arquivos.
        self.accept()
        QApplication.quit()

    def reject(self):
        # Não deixa fechar no meio do download (a thread ainda estaria rodando).
        if self.worker and self.worker.isRunning():
            return
        super(UpdateDialog, self).reject()
