# -*- coding: utf-8 -*-
"""Etapa 1 da revisão: grade de miniaturas de UMA classe por vez.

O revisor escolhe a classe numa aba (cada aba mostra o progresso da classe no lote) e fica
nela até terminar; ao terminar, vê o resumo da classe e escolhe a próxima. Cada marcação é salva
na hora como rascunho: trocar de aba, fechar ou cair no meio da página não perde nada.
Cada página começa com a pré-decisão do modelo; o revisor só corrige o que está errado:
  clique / Espaço   alterna aprovar <-> reprovar (miniatura sob o mouse)
  1..8 / botão dir. muda a classe (e aprova)
  Enter             confirma a página (grava) e abre a próxima; no resumo, vai para a próxima classe
  Z                 desfaz a última página confirmada
  E                 mostra o tile inteiro com a instância destacada
"""
from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygonF, QKeySequence
from PyQt5.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
                             QShortcut, QSizePolicy, QStackedWidget, QTabBar, QVBoxLayout, QWidget)

from libs.revisao import exportador

COLUNAS, LINHAS = 8, 5
POR_PAGINA = COLUNAS * LINHAS
CORES_CLASSE = [(0, 200, 0), (255, 0, 0), (255, 255, 0), (255, 128, 0), (220, 20, 60), (0, 120, 200),
                (255, 0, 255), (0, 255, 255)]
VERDE, VERMELHO = QColor(40, 200, 60), QColor(230, 40, 40)
MOTIVOS = {'baixa_conf': u'conf. baixa', 'fora_da_calcada': u'fora da calçada', 'veiculo': u'veículo'}


def cor_classe(classes, c):
    r, g, b = CORES_CLASSE[classes.index(c) % len(CORES_CLASSE)] if c in classes else (200, 200, 200)
    return QColor(r, g, b)


class Celula(QFrame):
    def __init__(self, grade, k):
        super(Celula, self).__init__()
        self.grade, self.k = grade, k
        self.item = None
        self.pix = None
        self.setMouseTracking(True)
        self.setMinimumSize(110, 110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def definir(self, item, pix):
        self.item, self.pix = item, pix
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(30, 30, 30))
        est = self.grade.estado.get(self.item['id']) if self.item is not None else None
        if est is None:
            return
        x = self.item
        lado = min(self.width(), self.height()) - 8
        r = QRectF((self.width() - lado) / 2.0, (self.height() - lado) / 2.0, lado, lado)
        if self.pix is not None:
            p.drawPixmap(r, self.pix, QRectF(self.pix.rect()))
        aprov = est['decisao'] == 'aprovar'
        if not aprov:
            p.fillRect(r, QColor(0, 0, 0, 120))
            p.setPen(QPen(VERMELHO, 3))
            p.drawLine(r.topLeft(), r.bottomRight())
            p.drawLine(r.topRight(), r.bottomLeft())
        foco = self.grade.foco == self.k
        p.setPen(QPen(VERDE if aprov else VERMELHO, 6 if foco else 3))
        p.drawRect(r.adjusted(1, 1, -1, -1))
        # rodapé: confiança e motivo da pré-reprovação
        f = QFont()
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        rod = QRectF(r.left(), r.bottom() - 16, r.width(), 16)
        p.fillRect(rod, QColor(0, 0, 0, 170))
        p.setPen(QColor(255, 255, 255))
        txt = u'%.2f' % x['conf']
        if x.get('motivo'):
            txt += u'  ' + MOTIVOS.get(x['motivo'], x['motivo'])
        p.drawText(rod.adjusted(4, 0, -2, 0), Qt.AlignVCenter | Qt.AlignLeft, txt)
        if est['classe'] != x['classe']:
            topo = QRectF(r.left(), r.top(), r.width(), 16)
            p.fillRect(topo, cor_classe(self.grade.classes, est['classe']))
            p.setPen(QColor(0, 0, 0))
            p.drawText(topo.adjusted(4, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, u'→ ' + est['classe'])
        p.end()

    def mousePressEvent(self, ev):
        if self.item is None:
            return
        if ev.button() == Qt.LeftButton:
            self.grade.alternar(self.k)
        elif ev.button() == Qt.RightButton:
            self.grade.menu_classe(self.k, ev.globalPos())

    def enterEvent(self, ev):
        self.grade.focar(self.k)


class Grade(QWidget):
    etapa_concluida = pyqtSignal()
    mudou = pyqtSignal()

    def __init__(self, parent=None):
        super(Grade, self).__init__(parent)
        self.proj = self.lote = None
        self.classes = []
        self.itens, self.estado = [], {}
        self.foco = -1
        self.paginas = []      # (classe, ids) das páginas confirmadas nesta sessão (para desfazer)
        self.cache_pix = {}
        self.classe = None     # classe em revisão (escolhida na aba)
        self.t_rascunho = QTimer(self, singleShot=True, interval=300, timeout=self.salvar_rascunho)

        v = QVBoxLayout(self)
        self.abas = QTabBar()
        self.abas.setExpanding(False)
        self.abas.setDrawBase(True)
        self.abas.currentChanged.connect(self._aba_clicada)
        v.addWidget(self.abas)
        topo = QHBoxLayout()
        self.lb_titulo = QLabel()
        f = self.lb_titulo.font()
        f.setPointSize(13)
        f.setBold(True)
        self.lb_titulo.setFont(f)
        topo.addWidget(self.lb_titulo, 1)
        self.b_desfazer = QPushButton(u'Desfazer página (Z)', clicked=self.desfazer)
        self.b_confirmar = QPushButton(u'Confirmar página  ⏎', clicked=self.confirmar)
        self.b_confirmar.setStyleSheet('font-weight: bold; padding: 6px 16px')
        topo.addWidget(self.b_desfazer)
        topo.addWidget(self.b_confirmar)
        v.addLayout(topo)
        ajuda = QLabel(u'<b>Clique/Espaço</b> alterna aprovar ↔ reprovar · <b>1–8</b> ou botão direito muda a classe · '
                       u'<b>Enter</b> confirma · <b>Z</b> desfaz · <b>E</b> vê o tile inteiro')
        ajuda.setStyleSheet('color: #555')
        v.addWidget(ajuda)
        self.pilha = QStackedWidget()
        pg = QWidget()
        meio = QHBoxLayout(pg)
        meio.setContentsMargins(0, 0, 0, 0)
        self.g = QGridLayout()
        self.g.setSpacing(4)
        self.celulas = []
        for k in range(POR_PAGINA):
            c = Celula(self, k)
            self.g.addWidget(c, k // COLUNAS, k % COLUNAS)
            self.celulas.append(c)
        meio.addLayout(self.g, 5)
        lado = QVBoxLayout()
        self.lb_det = QLabel(alignment=Qt.AlignCenter)
        self.lb_det.setFixedSize(300, 300)
        self.lb_det.setStyleSheet('background:#222')
        self.lb_info = QLabel(wordWrap=True, alignment=Qt.AlignTop)
        self.lb_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lado.addWidget(self.lb_det)
        lado.addWidget(self.lb_info, 1)
        meio.addLayout(lado, 0)
        self.pilha.addWidget(pg)

        # resumo de uma classe concluída
        res = QWidget()
        vr = QVBoxLayout(res)
        vr.addStretch(1)
        self.lb_res_titulo = QLabel(alignment=Qt.AlignCenter)
        f2 = self.lb_res_titulo.font()
        f2.setPointSize(18)
        f2.setBold(True)
        self.lb_res_titulo.setFont(f2)
        self.lb_res_texto = QLabel(alignment=Qt.AlignCenter)
        self.lb_res_texto.setTextFormat(Qt.RichText)
        self.b_seguir = QPushButton(clicked=self._seguir)
        self.b_seguir.setStyleSheet('font-weight: bold; padding: 10px 24px; font-size: 14px')
        vr.addWidget(self.lb_res_titulo)
        vr.addWidget(self.lb_res_texto)
        hb = QHBoxLayout()
        hb.addStretch(1)
        hb.addWidget(self.b_seguir)
        hb.addStretch(1)
        vr.addLayout(hb)
        vr.addStretch(2)
        self.pilha.addWidget(res)
        v.addWidget(self.pilha, 1)

        for tecla, fn in ((Qt.Key_Space, self._espaco), (Qt.Key_Return, self._enter), (Qt.Key_Enter, self._enter),
                          (Qt.Key_Z, self.desfazer), (Qt.Key_E, self._contexto)):
            QShortcut(QKeySequence(tecla), self, fn, context=Qt.WidgetWithChildrenShortcut)
        for n in range(1, 10):
            QShortcut(QKeySequence(str(n)), self, lambda n=n: self._reclassificar_foco(n - 1),
                      context=Qt.WidgetWithChildrenShortcut)

    # --- classes e páginas -----------------------------------------------------
    def abrir(self, proj, lote):
        self.proj, self.lote, self.classes = proj, lote, lote.classes
        self.paginas = []
        self.cache_pix = {}
        pend = lote.classes_pendentes()
        self.classe = pend[0] if pend else None
        self._montar_abas()
        self.mostrar()

    def _contagem(self, c):
        """(revisadas, total) da classe proposta c no lote."""
        ids = [i for i, x in self.lote.inst.items() if x['classe'] == c]
        return sum(1 for i in ids if i in self.proj.dec), len(ids)

    def _montar_abas(self):
        self.abas.blockSignals(True)
        while self.abas.count():
            self.abas.removeTab(0)
        for c in self.classes:
            feitas, total = self._contagem(c)
            if not total:
                continue
            k = self.abas.addTab(u'')
            self.abas.setTabData(k, c)
            self.abas.setTabTextColor(k, cor_classe(self.classes, c).darker(150))
        self.abas.blockSignals(False)
        self.abas.updateGeometry()     # a barra nasce vazia (altura 0): avisa o layout que agora tem abas
        self._atualizar_abas()

    def _atualizar_abas(self):
        self.abas.blockSignals(True)
        for k in range(self.abas.count()):
            c = self.abas.tabData(k)
            feitas, total = self._contagem(c)
            self.abas.setTabText(k, u'%s  %d/%d%s' % (c, feitas, total, u'  ✓' if feitas == total else u''))
            if c == self.classe:
                self.abas.setCurrentIndex(k)
        self.abas.blockSignals(False)

    def _aba_clicada(self, k):
        c = self.abas.tabData(k)
        if c is None or c == self.classe:
            return
        self.salvar_rascunho()        # a página desta classe volta igual quando o revisor retornar
        self.classe = c
        self.mostrar()

    def _chave(self):
        return u'grade|%s|%s' % (self.lote.nome, self.classe)

    def salvar_rascunho(self):
        """Grava as marcações da página que diferem da pré-decisão (chamado a cada mudança)."""
        self.t_rascunho.stop()
        if self.lote is None or self.classe is None or not self.itens:
            return
        mudou = {x['id']: self.estado[x['id']] for x in self.itens
                 if self.estado[x['id']] != {'decisao': x['pre'], 'classe': x['classe']}}
        self.proj.gravar_rascunho(self._chave(), mudou)

    def mostrar(self):
        """Página seguinte da classe escolhida, ou o resumo dela quando já foi toda revisada."""
        self._atualizar_abas()
        self.b_desfazer.setEnabled(bool(self.paginas))
        pend = self.lote.pendentes(self.classe) if self.classe else []
        if not pend:
            self._mostrar_resumo()
            return
        c = self.classe
        self.pilha.setCurrentIndex(0)
        self.b_confirmar.setEnabled(True)
        self.itens = pend[:POR_PAGINA]
        self.estado = {x['id']: {'decisao': x['pre'], 'classe': x['classe']} for x in self.itens}
        rasc = self.proj.rascunho(self._chave()) or {}
        for i, e in rasc.items():       # marcações feitas antes de fechar/trocar de aba
            if i in self.estado:
                self.estado[i] = dict(e)
        for k, cel in enumerate(self.celulas):
            x = self.itens[k] if k < len(self.itens) else None
            cel.definir(x, self._pix(x) if x else None)
        feitas, total = self._contagem(c)
        self.lb_titulo.setText(u'%s  ·  <span style="color:%s">%s</span>  ·  %d–%d de %d' % (
            self.lote.nome, cor_classe(self.classes, c).darker(140).name(), c, feitas + 1, feitas + len(self.itens), total))
        self.lb_titulo.setTextFormat(Qt.RichText)
        self.foco = -1
        self._detalhe(None)
        self.setFocus()
        self._precarregar(pend[POR_PAGINA:2 * POR_PAGINA])

    def _mostrar_resumo(self):
        self.itens, self.estado = [], {}
        for cel in self.celulas:
            cel.definir(None, None)
        self.pilha.setCurrentIndex(1)
        self.b_confirmar.setEnabled(False)
        c = self.classe
        aprov = reprov = 0
        outras = {}
        for i, x in self.lote.inst.items():
            d = self.proj.dec.get(i)
            if x['classe'] != c or d is None:
                continue
            if d['decisao'] == 'reprovar':
                reprov += 1
            elif d['classe'] == c:
                aprov += 1
            else:
                outras[d['classe']] = outras.get(d['classe'], 0) + 1
        recebidas = sum(1 for i, d in self.proj.dec.items() if d.get('lote') == self.lote.nome
                        and d['decisao'] == 'aprovar' and d['classe'] == c and d.get('classe_orig') != c)
        linhas = [u'<span style="color:#1e7a3c"><b>%d aprovadas</b></span> · '
                  u'<span style="color:#b3261e"><b>%d reprovadas</b></span>' % (aprov, reprov)]
        for oc, n in sorted(outras.items()):
            linhas.append(u'%d reclassificadas para <b>%s</b>' % (n, oc))
        if recebidas:
            linhas.append(u'%d vieram de outras classes' % recebidas)
        linhas.append(u'<br><span style="color:#777">Tudo já está gravado. Clique numa aba para rever outra classe; '
                      u'<b>Z</b> desfaz a última página.</span>')
        self.lb_res_titulo.setText(u'%s concluída' % c if c else u'Lote sem instâncias')
        self.lb_res_texto.setText(u'<br>'.join(linhas))
        prox = self._proxima_classe()
        if prox:
            self.b_seguir.setText(u'Próxima classe: %s (%d)  ⏎' % (prox, len(self.lote.pendentes(prox))))
        else:
            self.b_seguir.setText(u'Todas as classes revisadas: ir para a checagem dos tiles  ⏎')
        self.lb_titulo.setText(u'%s  ·  %s' % (self.lote.nome, c or ''))
        self.setFocus()

    def _proxima_classe(self):
        pend = self.lote.classes_pendentes()
        if not pend:
            return None
        if self.classe in self.classes:
            depois = [c for c in pend if self.classes.index(c) > self.classes.index(self.classe)]
            if depois:
                return depois[0]
        return pend[0]

    def _seguir(self):
        prox = self._proxima_classe()
        if prox:
            self.classe = prox
            self.mostrar()
        else:
            self.etapa_concluida.emit()

    def _enter(self):
        if self.pilha.currentIndex() == 1:
            self._seguir()
        else:
            self.confirmar()

    def _pix(self, x):
        if x['id'] not in self.cache_pix:
            self.cache_pix[x['id']] = QPixmap(x['miniatura_abs'])
        return self.cache_pix[x['id']]

    def _precarregar(self, itens):
        # miniaturas da próxima página (leve: ~10 KB cada, mas na rede a latência soma)
        for x in itens:
            self._pix(x)

    def confirmar(self):
        if not self.itens:
            return
        self._gravar_pagina()
        self.mostrar()

    def _gravar_pagina(self):
        regs, reprov = [], []
        for x in self.itens:
            e = self.estado[x['id']]
            regs.append({'tipo': 'instancia', 'id': x['id'], 'lote': self.lote.nome, 'tile': x['tile'],
                         'classe_orig': x['classe'], 'classe': e['classe'], 'decisao': e['decisao'],
                         'pre': x['pre'], 'motivo': x.get('motivo', ''), 'conf': x['conf'], 'origem': 'grade'})
            if e['decisao'] == 'reprovar':
                reprov.append(x)
        self.proj.registrar(regs)
        self.t_rascunho.stop()
        self.proj.gravar_rascunho(self._chave(), None)
        exportador.descartar_instancias(self.proj, reprov)
        self.paginas.append((self.classe, [x['id'] for x in self.itens]))
        for x in self.itens:
            self.cache_pix.pop(x['id'], None)
        self.itens, self.estado = [], {}
        self.mudou.emit()

    def desfazer(self):
        if not self.paginas:
            return
        classe, ids = self.paginas.pop()
        exportador.remover([self.proj.p('descarte', 'recortes', self.lote.inst[i]['classe'], i + '.jpg') for i in ids])
        self.proj.registrar([{'tipo': 'desfazer_instancias', 'ids': ids, 'lote': self.lote.nome}])
        self.classe = classe          # volta para a classe da página desfeita
        self.mudou.emit()
        self.mostrar()

    # --- interação -----------------------------------------------------------
    def alternar(self, k):
        if k >= len(self.itens):
            return
        e = self.estado[self.itens[k]['id']]
        e['decisao'] = 'reprovar' if e['decisao'] == 'aprovar' else 'aprovar'
        self.celulas[k].update()
        self._detalhe(self.itens[k])
        self.t_rascunho.start()

    def reclassificar(self, k, classe):
        if k >= len(self.itens) or classe not in self.classes:
            return
        e = self.estado[self.itens[k]['id']]
        e['classe'], e['decisao'] = classe, 'aprovar'
        self.celulas[k].update()
        self._detalhe(self.itens[k])
        self.t_rascunho.start()

    def _reclassificar_foco(self, i):
        if 0 <= self.foco < len(self.itens) and i < len(self.classes):
            self.reclassificar(self.foco, self.classes[i])

    def _espaco(self):
        if 0 <= self.foco < len(self.itens):
            self.alternar(self.foco)

    def menu_classe(self, k, pos):
        m = QMenu(self)
        for i, c in enumerate(self.classes):
            a = m.addAction(u'%d  %s' % (i + 1, c))
            a.setData(c)
        a = m.exec_(pos)
        if a is not None:
            self.reclassificar(k, a.data())

    def focar(self, k):
        antigo, self.foco = self.foco, k
        for i in (antigo, k):
            if 0 <= i < len(self.celulas):
                self.celulas[i].update()
        self._detalhe(self.itens[k] if k < len(self.itens) else None)

    def _detalhe(self, x):
        if x is None:
            self.lb_det.clear()
            self.lb_info.setText(u'')
            return
        pix = self._pix(x)
        self.lb_det.setPixmap(pix.scaled(self.lb_det.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        e = self.estado[x['id']]
        linhas = [u'<b>%s</b> → <b style="color:%s">%s</b>' % (x['classe'], 'green' if e['decisao'] == 'aprovar' else 'red',
                                                               'APROVAR' if e['decisao'] == 'aprovar' else 'REPROVAR'),
                  u'confiança %.2f  (SAM %.2f, DINOv2 %.2f)' % (x['conf'], x['score'], x.get('p_dino', 0)),
                  u'prompt: %s' % x.get('prompt', '')]
        if e['classe'] != x['classe']:
            linhas.append(u'nova classe: <b>%s</b>' % e['classe'])
        if x.get('motivo'):
            linhas.append(u'pré-reprovada: %s' % MOTIVOS.get(x['motivo'], x['motivo']))
        if x.get('sinais'):
            linhas.append(u'sinais: %s' % ', '.join(x['sinais']))
        linhas.append(u'<span style="color:#777">%s</span>' % x['tile'])
        self.lb_info.setText(u'<br>'.join(linhas))

    def _contexto(self):
        if 0 <= self.foco < len(self.itens):
            ContextoTile(self, self.lote, self.itens[self.foco]).exec_()


class ContextoTile(QDialog):
    """Tile inteiro com a instância destacada (tecla E na grade)."""

    def __init__(self, parent, lote, x):
        super(ContextoTile, self).__init__(parent)
        self.setWindowTitle(x['tile'])
        tile = lote.tile_por_nome[x['tile']]
        pix = QPixmap(tile['caminho'])
        alvo = 900
        k = float(alvo) / max(pix.width(), pix.height())
        pix = pix.scaled(int(pix.width() * k), int(pix.height() * k), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 0), 3))
        p.drawPolygon(QPolygonF([QPointF(a * k, b * k) for a, b in x['poligono']]))
        p.end()
        v = QVBoxLayout(self)
        lb = QLabel()
        lb.setPixmap(pix)
        v.addWidget(lb)
        QShortcut(QKeySequence(Qt.Key_E), self, self.accept)
