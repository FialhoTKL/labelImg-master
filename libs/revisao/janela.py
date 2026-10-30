# -*- coding: utf-8 -*-
"""Janela do modo revisão: lista de lotes + grade (etapa 1) + checagem do tile (etapa 2)."""
import os
from collections import Counter

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QAbstractItemView, QDockWidget, QHeaderView, QLabel, QMainWindow, QMessageBox,
                             QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from libs.revisao.checagem import Checagem
from libs.revisao.grade import Grade
from libs.revisao.projeto import ProjetoRevisao


class JanelaRevisao(QMainWindow):
    def __init__(self, raiz, parent=None):
        super(JanelaRevisao, self).__init__(parent)
        self.proj = ProjetoRevisao(raiz)
        self.lote = None
        # o Canvas consulta estes dois atributos na janela
        self.file_path = None
        self.label_coordinates = QLabel('')
        self.statusBar().addPermanentWidget(self.label_coordinates)
        self.setWindowTitle(u'Revisão — %s' % os.path.basename(self.proj.raiz))
        self.resize(1500, 950)

        self.pilha = QStackedWidget()
        self.inicio = QLabel(u'Escolha um lote à esquerda (duplo clique).', alignment=Qt.AlignCenter)
        self.grade = Grade()
        self.checagem = Checagem()
        for w in (self.inicio, self.grade, self.checagem):
            self.pilha.addWidget(w)
        self.setCentralWidget(self.pilha)
        self.grade.etapa_concluida.connect(self._etapa_concluida)
        self.checagem.etapa_concluida.connect(self._etapa_concluida)
        self.grade.mudou.connect(self.atualizar)
        self.checagem.mudou.connect(self.atualizar)

        dock = QDockWidget(u'Lotes', self)
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        w = QWidget()
        v = QVBoxLayout(w)
        self.tb = QTableWidget(0, 3)
        self.tb.setHorizontalHeaderLabels([u'Lote', u'Etapa', u'Progresso'])
        self.tb.verticalHeader().setVisible(False)
        self.tb.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tb.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tb.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tb.cellDoubleClicked.connect(lambda r, c: self.abrir_lote(self.tb.item(r, 0).text()))
        v.addWidget(self.tb, 1)
        v.addWidget(QPushButton(u'Abrir próximo lote pendente', clicked=self.abrir_proximo))
        self.lb_met = QLabel(wordWrap=True)
        self.lb_met.setTextFormat(Qt.RichText)
        v.addWidget(self.lb_met)
        w.setMinimumWidth(340)
        dock.setWidget(w)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        # lotes novos chegam do processador pela rede
        self.timer = QTimer(self, interval=30000, timeout=self.atualizar)
        self.timer.start()
        self.atualizar()
        QTimer.singleShot(0, self.abrir_proximo)

    # --- lotes ------------------------------------------------------------------
    def _resumo_lote(self, l, feitas_por_lote, tiles_por_lote):
        """(etapa, progresso) sem carregar o lote inteiro: lote.json + decisões."""
        if not l['fechado']:
            return u'Processando', u'', '#999'
        if l['estado'] == 'concluido':
            return u'Concluído', u'', '#2a7'
        info = self.proj.info_lote(l['nome'])
        total = sum(v['total'] for v in info.get('resumo', {}).values())
        feitas = feitas_por_lote.get(l['nome'], 0)
        if feitas < total:
            return u'1 · Grade', u'%d / %d instâncias' % (feitas, total), '#27c' if feitas else '#000'
        return u'2 · Checagem', u'%d tiles conferidos' % tiles_por_lote.get(l['nome'], 0), '#c80'

    def atualizar(self):
        # lote parado esperando a GPU: retoma sozinho quando as respostas chegam
        if self.lote is not None and self.pilha.currentWidget() is self.inicio and self.lote.etapa() != 'aguardando':
            self._seguir()
        todos = self.proj.lotes()
        # a tabela mostra os lotes prontos e os próximos em processamento; o resto vira uma linha de resumo
        abertos = [l for l in todos if not l['fechado']]
        lotes = [l for l in todos if l['fechado']] + abertos[:3]
        resto = len(abertos) - min(len(abertos), 3)
        feitas_por_lote = Counter(d.get('lote') for d in self.proj.dec.values())
        tiles_por_lote = Counter(r.get('lote') for r in self.proj.tiles.values())
        self.tb.setRowCount(len(lotes) + (1 if resto else 0))
        if resto:
            for j, txt in enumerate((u'+ %d lotes' % resto, u'Aguardando', u'processamento')):
                it = QTableWidgetItem(txt)
                it.setForeground(QColor('#999'))
                self.tb.setItem(len(lotes), j, it)
        for i, l in enumerate(lotes):
            etapa, prog, cor = self._resumo_lote(l, feitas_por_lote, tiles_por_lote)
            for j, txt in enumerate((l['nome'], etapa, prog)):
                it = QTableWidgetItem(txt)
                it.setForeground(QColor(cor))
                if self.lote is not None and l['nome'] == self.lote.nome:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.tb.setItem(i, j, it)
        m = self.proj.metricas()
        linhas = [u'<b>Revisor:</b> %s' % self.proj.revisor,
                  u'<b>Decisões:</b> %d (%d na última hora)' % (m['total'], m['ultima_hora']),
                  u'<b>Tiles no dataset:</b> %d' % m['tiles'], u'<br><b>Aprovação por classe</b>']
        for c in self.proj.classes:
            v = m['por_classe'].get(c)
            if v:
                n = v['aprovar'] + v['reprovar']
                linhas.append(u'%s: %d%% de %d' % (c, round(100.0 * v['aprovar'] / n), n))
        self.lb_met.setText(u'<br>'.join(linhas))

    def abrir_proximo(self):
        for l in self.proj.lotes():
            if l['fechado'] and l['estado'] != 'concluido':
                self.abrir_lote(l['nome'])
                return
        self.pilha.setCurrentWidget(self.inicio)
        self.inicio.setText(u'Nenhum lote pendente. Lotes novos aparecem aqui quando o processador fecha.')

    def abrir_lote(self, nome):
        l = next((x for x in self.proj.lotes() if x['nome'] == nome), None)
        if l is None or not l['fechado']:
            QMessageBox.information(self, u'Lote', u'Esse lote ainda está sendo processado.')
            return
        self.lote = self.proj.lote(nome)
        self.statusBar().showMessage(u'%s: %d tiles, %d instâncias' % (nome, len(self.lote.tiles), len(self.lote.inst)))
        self._seguir()
        self.atualizar()

    def _seguir(self):
        etapa = self.lote.etapa()
        if etapa == 'grade':
            self.pilha.setCurrentWidget(self.grade)
            self.grade.abrir(self.proj, self.lote)
        elif etapa == 'checagem':
            self.pilha.setCurrentWidget(self.checagem)
            self.checagem.abrir(self.proj, self.lote)
        elif etapa == 'aguardando':
            n = len(self.lote.aguardando())
            self.pilha.setCurrentWidget(self.inicio)
            self.inicio.setText(u'%s: %d tile(s) aguardando a máscara do SAM na GPU.\n'
                                u'Eles voltam para conferência quando o processador responder '
                                u'(o processador precisa estar rodando).' % (self.lote.nome, n))
        else:
            if self.proj.estado_lote.get(self.lote.nome) != 'concluido':
                self.proj.registrar([{'tipo': 'lote', 'lote': self.lote.nome, 'estado': 'concluido'}])
            self.statusBar().showMessage(u'%s concluído.' % self.lote.nome, 8000)
            self.atualizar()
            self.abrir_proximo()

    def _etapa_concluida(self):
        self._seguir()
