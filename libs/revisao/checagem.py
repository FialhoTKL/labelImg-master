# -*- coding: utf-8 -*-
"""Etapa 2 da revisão: o tile inteiro com os polígonos aprovados, para conferir se está completo.

Perfil Rostos e placas: pessoas e veículos achados pelo SAM aparecem em caixas tracejadas laranja (só
dica, não vão para o dataset). Tile sem nada aprovado mas com pessoa/veículo também vem para cá
(conferência): Enter confirma que não há rosto/placa visível; B marca o que o modelo deixou passar.

  Enter    completo: grava o tile no dataset e abre o próximo
  P        desenha um polígono do objeto que faltou (escolhe a classe em seguida)
  B        caixa do que faltou: a GPU devolve a máscara do SAM (o tile volta para conferência depois)
  G        cobre de cinza uma região duvidosa (retângulo; o YOLO não aprende nada ali)
  Delete   apaga o polígono selecionado (a instância vira reprovada)
  X        descarta o tile inteiro
  Z        desfaz o último tile
  Ctrl+Z   desfaz a última edição de polígono neste tile (um passo por vez)
  F        ajusta o zoom à janela (roda do mouse = zoom no ponto do mouse, arrastar o fundo = mover)
Vértices: clique apaga, arrastar move. Botão direito com um polígono selecionado insere um vértice no
ponto; sem nada selecionado começa um polígono novo ali (a classe é escolhida ao fechar). Esc tira a seleção.
Cada mudança no tile é salva na hora como rascunho: fechar ou cair antes do Enter não perde nada.
"""
from PyQt5.QtCore import QEvent, QPointF, Qt, QTimer, pyqtSignal
from collections import Counter

from PyQt5.QtGui import QColor, QCursor, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea,
                             QShortcut, QVBoxLayout, QWidget)

from libs.canvas import Canvas
from libs.revisao import exportador
from libs.revisao.grade import cor_classe
from libs.shape import POLYGON, RECTANGLE, Shape

CINZA = '__cinza__'
NOMES_DICA = {'person': u'pessoa', 'car': u'carro', 'truck': u'caminhão', 'bus': u'ônibus',
              'motorcycle': u'moto'}


class ShapeCinza(Shape):
    """Região a cobrir de cinza no tile exportado: sempre preenchida."""

    def paint(self, painter):
        self.fill = True
        super(ShapeCinza, self).paint(painter)


class Checagem(QWidget):
    etapa_concluida = pyqtSignal()
    mudou = pyqtSignal()

    def __init__(self, parent=None):
        super(Checagem, self).__init__(parent)
        self.proj = self.lote = self.tile = None
        self.feitos = []          # tiles decididos nesta sessão (para desfazer)
        self.modo = None          # None | 'cinza' | 'caixa' (o que a próxima forma desenhada significa)
        self.t_rascunho = QTimer(self, singleShot=True, interval=500, timeout=self.salvar_rascunho)
        # Ctrl+Z: pilha de estados do tile; um arrasto inteiro (do clique ao soltar) é um passo só
        self.historico = []
        self._base = []
        self._grupo = False

        v = QVBoxLayout(self)
        topo = QHBoxLayout()
        self.lb_titulo = QLabel(wordWrap=True)
        f = self.lb_titulo.font()
        f.setPointSize(13)
        f.setBold(True)
        self.lb_titulo.setFont(f)
        topo.addWidget(self.lb_titulo, 1)
        for txt, fn in ((u'Desfazer tile (Z)', self.desfazer), (u'Descartar tile (X)', self.descartar),
                        (u'Completo  ⏎', self.confirmar)):
            b = QPushButton(txt, clicked=fn)
            topo.addWidget(b)
        self.b_ok = b
        self.b_ok.setStyleSheet('font-weight: bold; padding: 6px 16px')
        v.addLayout(topo)
        ajuda = QLabel(u'<b>Enter</b> completo · <b>P</b> polígono do que faltou · <b>B</b> caixa → SAM · '
                       u'<b>G</b> cobrir de cinza · '
                       u'<b>Delete</b> apaga o selecionado · <b>X</b> descarta o tile · <b>Z</b> desfaz o tile · '
                       u'<b>Ctrl+Z</b> desfaz a edição · '
                       u'<b>F</b> ajusta o zoom<br>Vértice: <b>clique</b> apaga, arrastar move · '
                       u'<b>botão direito</b>: com polígono selecionado insere vértice, sem seleção começa '
                       u'polígono novo · <b>Esc</b> tira a seleção')
        ajuda.setStyleSheet('color: #555')
        ajuda.setWordWrap(True)      # sem quebra a linha longa alarga a janela além da tela
        v.addWidget(ajuda)

        self.canvas = Canvas(parent=self)
        self.canvas.edicao_rapida = True
        self.canvas.newShape.connect(self._nova_forma)
        self.canvas.drawingPolygon.connect(self._desenhando)
        self.canvas.shapeMoved.connect(self._mexeu)
        self.canvas.zoomRequest.connect(self._zoom)
        self.canvas.installEventFilter(self)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(True)
        self.canvas.scrollRequest.connect(self._rolar)
        meio = QHBoxLayout()
        meio.addWidget(self.scroll, 1)
        # o que o tile tem, por classe: o revisor sabe o que procurar; clicar seleciona o próximo da classe
        lado = QVBoxLayout()
        lado.addWidget(QLabel(u'<b>Neste tile</b>'))
        self.lista = QListWidget()
        self.lista.setFixedWidth(220)
        self.lista.setFocusPolicy(Qt.NoFocus)        # as teclas continuam indo para o tile
        self.lista.itemClicked.connect(self._ir_para_classe)
        lado.addWidget(self.lista, 1)
        dica = QLabel(u'Clique numa classe para ver cada objeto dela.', wordWrap=True)
        dica.setStyleSheet('color: #555')
        dica.setFixedWidth(220)
        lado.addWidget(dica)
        meio.addLayout(lado)
        v.addLayout(meio, 1)

        atalhos = ((Qt.Key_Return, self._enter), (Qt.Key_Enter, self._enter), (Qt.Key_P, self.novo_poligono),
                   (Qt.Key_G, self.cobrir_cinza), (Qt.Key_B, self.caixa_sam), (Qt.Key_Delete, self.apagar), (Qt.Key_X, self.descartar),
                   (Qt.Key_Z, self.desfazer), (Qt.Key_F, self.ajustar))
        for tecla, fn in atalhos:
            QShortcut(QKeySequence(tecla), self, fn, context=Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence('Ctrl+Z'), self, self.desfazer_edicao, context=Qt.WidgetWithChildrenShortcut)

    # --- fila de tiles -------------------------------------------------------
    def abrir(self, proj, lote):
        self.proj, self.lote = proj, lote
        self.feitos = []
        self.proximo()

    def proximo(self):
        pend = self.lote.tiles_pendentes()
        if not pend:
            self.etapa_concluida.emit()
            return
        self.mostrar(pend[0])

    def mostrar(self, tile):
        self.salvar_rascunho()
        self.alterado = False
        self.tile = tile
        pix = QPixmap(tile['caminho'])
        self.canvas.load_pixmap(pix)
        formas = []
        salvo = self.proj.tiles.get(tile['nome'])
        rasc = self.proj.rascunho(self._chave())
        if rasc:
            # o tile foi editado antes de fechar (ou foi desfeito): volta exatamente como estava
            formas = [self._de_rascunho(d) for d in rasc]
        elif salvo and salvo['estado'] == 'aguardando':
            # volta do pedido: o que já estava conferido + os polígonos que a GPU devolveu
            for p in salvo['poligonos']:
                formas.append(self._forma(p['classe'], p['pontos'], p.get('id')))
                if p.get('editado'):
                    formas[-1].pontos_orig = None
            for pid in salvo['pedidos']:
                r = self.lote.resposta(pid)
                if r:
                    formas.append(self._forma(r['classe'], r['poligono']))
                    formas[-1].pontos_orig = None
            for x0, y0, x1, y1 in salvo.get('cinza', []):
                formas.append(self._cinza([QPointF(x0, y0), QPointF(x1, y0), QPointF(x1, y1), QPointF(x0, y1)]))
        else:
            for x, classe in self.lote.aprovadas(tile['nome']):
                formas.append(self._forma(classe, x['poligono'], x['id']))
        self._i_dica = -1
        self.canvas.dicas = [tuple(d['caixa']) + (NOMES_DICA.get(d['prompt'], d['prompt']),)
                             for d in tile.get('conferir', [])]
        self.canvas.load_shapes(formas)
        self.canvas.set_editing(True)
        self.historico = []
        self._base = self._estado()
        self._grupo = False
        prog = self.lote.progresso()['tiles']
        conf = u'CONFERIR: há rosto ou placa que o modelo não marcou?  ·  ' if self.lote.a_conferir(tile['nome']) else u''
        self.lb_titulo.setText(u'%s%s  ·  tile %d de %d  ·  %s  ·  %d objetos' % (
            conf, self.lote.nome, prog[0] + 1, prog[1], tile['nome'], len(formas)))
        self._atualizar_lista()
        self.ajustar()
        self.canvas.setFocus()

    def _forma(self, classe, pontos, inst_id=None):
        s = Shape(label=classe, shape_type=POLYGON)
        for a, b in pontos:
            s.add_point(QPointF(a, b))
        s.close()
        cor = cor_classe(self.lote.classes, classe)
        s.line_color = cor
        s.fill_color = QColor(cor.red(), cor.green(), cor.blue(), 70)
        s.paint_label = True
        s.inst_id = inst_id
        s.pontos_orig = [tuple(p) for p in pontos]
        return s

    # --- rascunho -------------------------------------------------------------
    def _chave(self, nome=None):
        return u'tile|%s|%s' % (self.lote.nome, nome or self.tile['nome'])

    def _para_rascunho(self, s):
        tipo = 'cinza' if s.label == CINZA else 'caixa' if getattr(s, 'pedido', False) else 'poligono'
        return {'tipo': tipo, 'classe': s.label, 'id': getattr(s, 'inst_id', None),
                'editado': tipo == 'poligono' and self._editado(s),
                'pontos': [[round(p.x(), 1), round(p.y(), 1)] for p in s.points]}

    def _de_rascunho(self, d):
        pts = [QPointF(a, b) for a, b in d['pontos']]
        if d['tipo'] == 'cinza':
            return self._cinza(pts)
        if d['tipo'] == 'caixa':
            return self._caixa(d['classe'], pts)
        s = self._forma(d['classe'], d['pontos'], d.get('id'))
        if d.get('editado'):
            s.pontos_orig = None
        return s

    def _caixa(self, classe, pontos):
        s = Shape(label=classe, shape_type=RECTANGLE)
        s.points = list(pontos)
        s.close()
        s.pedido = True          # vira pedido de máscara ao confirmar o tile
        s.line_color = QColor(0, 160, 255)
        s.fill_color = QColor(0, 160, 255, 40)
        s.paint_label = True
        return s

    def _mexeu(self):
        self._marcar()
        self.alterado = True
        self.t_rascunho.start()       # arrastar vértice emite a cada movimento: grava 0,5 s depois de parar

    def salvar_rascunho(self):
        """Grava as formas atuais do tile, se o revisor mexeu nele (tile intocado não gera rascunho)."""
        self.t_rascunho.stop()
        if self.tile is None or self.lote is None or not getattr(self, 'alterado', False):
            return
        self.proj.gravar_rascunho(self._chave(), [self._para_rascunho(s) for s in self.canvas.shapes])

    def _limpar_rascunho(self):
        self.t_rascunho.stop()
        self.proj.gravar_rascunho(self._chave(), None)

    # --- decisões ------------------------------------------------------------
    def _cinza(self, pontos):
        g = ShapeCinza(label=CINZA)
        g.points = list(pontos)
        g.close()
        g.line_color = QColor(114, 114, 114)
        g.fill_color = QColor(114, 114, 114, 200)
        return g

    def _formas(self):
        return [s for s in self.canvas.shapes if s.label != CINZA and not getattr(s, 'pedido', False)]

    def confirmar(self):
        if self.tile is None or self.canvas.current is not None:
            return
        formas = self._formas()
        poligonos = [(s.label, [(p.x(), p.y()) for p in s.points]) for s in formas]
        cinza = []
        for s in self.canvas.shapes:
            if s.label == CINZA:
                r = s.bounding_rect()
                cinza.append((r.left(), r.top(), r.right(), r.bottom()))
        caixas = [s for s in self.canvas.shapes if getattr(s, 'pedido', False)]
        if caixas:
            self._aguardar(formas, cinza, caixas)
            return
        split, arquivos = exportador.exportar_tile(self.proj, self.tile, poligonos, cinza)
        regs = self._apagadas(formas)
        regs.append({'tipo': 'tile', 'lote': self.lote.nome, 'tile': self.tile['nome'], 'estado': 'completo',
                     'split': split, 'arquivos': arquivos, 'cinza': cinza,
                     'apagadas': [r['id'] for r in regs],
                     'poligonos': [{'classe': s.label, 'id': getattr(s, 'inst_id', None),
                                    'editado': self._editado(s),
                                    'pontos': [[round(p.x(), 1), round(p.y(), 1)] for p in s.points]} for s in formas]})
        self.proj.registrar(regs)
        self._limpar_rascunho()
        self.feitos.append(self.tile['nome'])
        self.tile = None
        self.mudou.emit()
        self.proximo()

    def _aguardar(self, formas, cinza, caixas):
        """Tile com caixas para o SAM: guarda o que já foi conferido e segue; volta quando a GPU responder."""
        pedidos, arquivos = [], []
        anteriores = len(self.proj.tiles.get(self.tile['nome'], {}).get('pedidos', []))
        for n, s in enumerate(caixas):
            r = s.bounding_rect()
            pid, arq = exportador.criar_pedido(self.proj, self.lote.nome, self.tile,
                                               (r.left(), r.top(), r.right(), r.bottom()), s.label, anteriores + n)
            pedidos.append(pid)
            arquivos.append(arq)
        regs = self._apagadas(formas)
        regs.append({'tipo': 'tile', 'lote': self.lote.nome, 'tile': self.tile['nome'], 'estado': 'aguardando',
                     'pedidos': pedidos, 'arquivos': arquivos, 'cinza': cinza, 'apagadas': [r['id'] for r in regs],
                     'poligonos': [{'classe': s.label, 'id': getattr(s, 'inst_id', None), 'editado': self._editado(s),
                                    'pontos': [[round(p.x(), 1), round(p.y(), 1)] for p in s.points]} for s in formas]})
        self.proj.registrar(regs)
        self._limpar_rascunho()
        self.feitos.append(self.tile['nome'])
        self.tile = None
        self.mudou.emit()
        self.proximo()

    def _apagadas(self, formas):
        """Instâncias aprovadas na grade que o revisor apagou aqui: viram reprovadas (aprendizado)."""
        vivos = {getattr(s, 'inst_id', None) for s in formas}
        regs = []
        for x, classe in self.lote.aprovadas(self.tile['nome']):
            if x['id'] not in vivos:
                regs.append({'tipo': 'instancia', 'id': x['id'], 'lote': self.lote.nome, 'tile': x['tile'],
                             'classe_orig': x['classe'], 'classe': classe, 'decisao': 'reprovar',
                             'pre': x['pre'], 'conf': x['conf'], 'origem': 'checagem'})
        return regs

    @staticmethod
    def _editado(s):
        orig = getattr(s, 'pontos_orig', None)
        if orig is None:
            return True     # polígono novo, desenhado à mão
        pts = [(p.x(), p.y()) for p in s.points]
        return len(pts) != len(orig) or any(abs(a - c) > 0.5 or abs(b - d) > 0.5 for (a, b), (c, d) in zip(pts, orig))

    def descartar(self):
        if self.tile is None:
            return
        arquivos = exportador.descartar_tile(self.proj, self.tile)
        self.proj.registrar([{'tipo': 'tile', 'lote': self.lote.nome, 'tile': self.tile['nome'],
                              'estado': 'descartado', 'arquivos': arquivos}])
        self._limpar_rascunho()
        self.feitos.append(self.tile['nome'])
        self.tile = None
        self.mudou.emit()
        self.proximo()

    def desfazer(self):
        if not self.feitos:
            return
        self.salvar_rascunho()
        nome = self.feitos.pop()
        r = self.proj.tiles.get(nome, {})
        exportador.remover(r.get('arquivos'))
        if r.get('estado') in ('completo', 'aguardando'):
            # reabre o tile com as edições que tinham sido gravadas, não com o original da grade
            formas = [{'tipo': 'poligono', 'classe': p['classe'], 'id': p.get('id'), 'editado': p.get('editado'),
                       'pontos': p['pontos']} for p in r.get('poligonos', [])]
            formas += [{'tipo': 'cinza', 'classe': CINZA, 'pontos': [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}
                       for x0, y0, x1, y1 in r.get('cinza', [])]
            self.proj.gravar_rascunho(self._chave(nome), formas)
        regs = [{'tipo': 'desfazer_tile', 'tile': nome, 'lote': self.lote.nome}]
        # instâncias apagadas nesta checagem voltam a ser aprovadas (com a classe da grade)
        for i in r.get('apagadas', []):
            d = self.proj.dec.get(i)
            if d:
                regs.append(dict(d, decisao='aprovar', origem='desfazer_checagem'))
        self.proj.registrar([{k: v for k, v in reg.items() if k not in ('t', 'rev')} for reg in regs])
        self.mudou.emit()
        self.mostrar(self.lote.tile_por_nome[nome])

    # --- edição -------------------------------------------------------------
    def _enter(self):
        c = self.canvas
        if c.current is not None:        # Enter fecha o polígono em desenho
            if c.can_close_shape():
                c.finalise()
            return
        self.confirmar()

    def novo_poligono(self):
        self.modo = None
        self.canvas.create_type = POLYGON
        self.canvas.set_editing(False)

    def cobrir_cinza(self):
        self.modo = 'cinza'
        self.canvas.create_type = RECTANGLE
        self.canvas.set_editing(False)

    def caixa_sam(self):
        self.modo = 'caixa'
        self.canvas.create_type = RECTANGLE
        self.canvas.set_editing(False)

    def apagar(self):
        if self.canvas.selected_shape is not None:
            self._marcar()
            self.canvas.delete_selected()
            self.canvas.update()
            self._atualizar_lista()
            self._assentar()
            self.alterado = True
            self.salvar_rascunho()

    def _desenhando(self, ativo):
        if not ativo:
            self.modo = None          # desenho cancelado (Esc): o próximo polígono não herda cinza/caixa
            self.canvas.set_editing(True)

    def _nova_forma(self):
        c = self.canvas
        s = c.shapes.pop()
        if self.modo == 'cinza':
            self._marcar()
            c.shapes.append(self._cinza(s.points))
        else:
            m = QMenu(self)
            for i, cl in enumerate(self.lote.classes):
                a = m.addAction(u'&%d  %s' % (i + 1, cl))
                a.setData(cl)
            a = m.exec_(QCursor.pos())
            if a is not None:
                self._marcar()
            if a is not None and self.modo == 'caixa':
                c.shapes.append(self._caixa(a.data(), s.points))
            elif a is not None:
                c.shapes.append(self._forma(a.data(), [(p.x(), p.y()) for p in s.points]))
                c.shapes[-1].pontos_orig = None
        self.modo = None
        c.set_editing(True)
        c.update()
        self._atualizar_lista()
        self._assentar()
        self.alterado = True
        self.salvar_rascunho()

    # --- desfazer edição (Ctrl+Z) --------------------------------------------
    def _estado(self):
        return [self._para_rascunho(s) for s in self.canvas.shapes]

    def _marcar(self):
        """Uma edição começou: guarda o estado de antes (só uma vez por gesto)."""
        if not self._grupo:
            self.historico.append(self._base)
            del self.historico[:-100]
            self._grupo = True

    def _assentar(self):
        """O gesto terminou (soltou o mouse/tecla): o estado atual vira a base do próximo passo."""
        if self._grupo and self.tile is not None:
            self._base = self._estado()
            self._grupo = False

    def eventFilter(self, obj, ev):
        if obj is self.canvas and ev.type() in (QEvent.MouseButtonRelease, QEvent.KeyRelease):
            QTimer.singleShot(0, self._assentar)      # depois que o canvas tratar o soltar
        return False

    def desfazer_edicao(self):
        c = self.canvas
        if c.current is not None:          # desenhando: tira o último vértice
            if c.current.is_polygon() and len(c.current) > 1:
                c.current.pop_point()
                c.line.points = [c.current[-1], c.line[1]]
                c.update()
            return
        self._assentar()
        if self.tile is None or not self.historico:
            return
        self._base = self.historico.pop()
        c.load_shapes([self._de_rascunho(d) for d in self._base])
        c.selected_shape = None
        c.un_highlight()
        c.update()
        self._atualizar_lista()
        self.alterado = True
        self.salvar_rascunho()

    # --- lista de classes do tile -------------------------------------------
    def _atualizar_lista(self):
        formas = self._formas()
        n = Counter(s.label for s in formas)
        self.lista.clear()
        for classe in sorted(n, key=lambda k: (-n[k], k)):
            pm = QPixmap(14, 14)
            pm.fill(cor_classe(self.lote.classes, classe))
            it = QListWidgetItem(QIcon(pm), u'%s   %d' % (classe, n[classe]))
            it.setData(Qt.UserRole, classe)
            self.lista.addItem(it)
        extras = [(u'caixas → SAM', sum(1 for s in self.canvas.shapes if getattr(s, 'pedido', False))),
                  (u'regiões cinza', sum(1 for s in self.canvas.shapes if s.label == CINZA))]
        for txt, k in extras:
            if k:
                it = QListWidgetItem(u'%s   %d' % (txt, k))
                it.setForeground(QColor(110, 110, 110))
                self.lista.addItem(it)
        if not formas:
            self.lista.addItem(QListWidgetItem(u'nenhum objeto aprovado'))
        n_dica = Counter(d[4] for d in self.canvas.dicas)
        for nome in sorted(n_dica, key=lambda k: (-n_dica[k], k)):
            it = QListWidgetItem(u'%s   %d  (conferir)' % (nome, n_dica[nome]))
            it.setForeground(QColor(220, 120, 0))
            it.setData(Qt.UserRole, (u'dica', nome))
            self.lista.addItem(it)
        self.lb_titulo.setText(self.lb_titulo.text().rsplit(u'  ·  ', 1)[0] + u'  ·  %d objetos' % len(formas))

    def _ir_para_classe(self, it):
        """Seleciona o próximo objeto da classe (circular) e rola a vista até ele."""
        classe = it.data(Qt.UserRole)
        if not classe:
            return
        c = self.canvas
        if isinstance(classe, (tuple, list)):
            self._ir_para_dica(classe[1])
            return
        formas = [s for s in self._formas() if s.label == classe]
        if not formas:
            return
        atual = formas.index(c.selected_shape) if c.selected_shape in formas else -1
        s = formas[(atual + 1) % len(formas)]
        c.select_shape(s)
        r = s.bounding_rect()
        off = c.offset_to_center()
        meio = (r.center() + off) * c.scale
        self.scroll.ensureVisible(int(meio.x()), int(meio.y()),
                                  int(r.width() * c.scale / 2) + 40, int(r.height() * c.scale / 2) + 40)
        c.setFocus()

    def _ir_para_dica(self, nome):
        """Próxima pessoa/veículo (circular): zoom de perto, para ver se há rosto ou placa."""
        c = self.canvas
        caixas = [d for d in c.dicas if d[4] == nome]
        if not caixas:
            return
        self._i_dica = (getattr(self, '_i_dica', -1) + 1) % len(caixas)
        x0, y0, x1, y1, _ = caixas[self._i_dica]
        vp = self.scroll.viewport()
        # a caixa ocupa ~60% da vista, sem passar de 4x
        c.scale = min(4.0, 0.6 * min(vp.width() / max(x1 - x0, 1.0), vp.height() / max(y1 - y0, 1.0)))
        c.resize(max(vp.width(), int(c.pixmap.width() * c.scale)), max(vp.height(), int(c.pixmap.height() * c.scale)))
        meio = (QPointF((x0 + x1) / 2.0, (y0 + y1) / 2.0) + c.offset_to_center()) * c.scale
        self.scroll.horizontalScrollBar().setValue(int(meio.x() - vp.width() / 2.0))
        self.scroll.verticalScrollBar().setValue(int(meio.y() - vp.height() / 2.0))
        c.update()
        c.setFocus()

    # --- zoom ---------------------------------------------------------------
    def ajustar(self):
        pm = self.canvas.pixmap
        if pm is None or pm.isNull():
            return
        vw, vh = self.scroll.viewport().width() - 2.0, self.scroll.viewport().height() - 2.0
        self.canvas.scale = min(vw / pm.width(), vh / pm.height())
        self.canvas.adjustSize()
        self.canvas.update()

    def _zoom(self, delta):
        """Zoom mantendo parado o pixel da imagem que está sob o mouse."""
        c = self.canvas
        tela = c.pos_roda
        if tela is None:      # sem roda ainda: centro da área visível
            vp = self.scroll.viewport()
            tela = QPointF(c.mapFrom(vp, vp.rect().center()))
        na_vista = tela + QPointF(c.pos())          # ponto do mouse na área visível
        ponto = tela / c.scale - c.offset_to_center()
        c.scale = min(max(c.scale * 1.15 ** (delta / 120.0), 0.05), 8.0)
        # já no tamanho final (a área de rolagem estica o canvas até a vista): o centramento sai certo
        vp = self.scroll.viewport()
        c.resize(max(vp.width(), int(c.pixmap.width() * c.scale)), max(vp.height(), int(c.pixmap.height() * c.scale)))
        novo = (ponto + c.offset_to_center()) * c.scale
        self.scroll.horizontalScrollBar().setValue(int(round(novo.x() - na_vista.x())))
        self.scroll.verticalScrollBar().setValue(int(round(novo.y() - na_vista.y())))
        c.pos_roda = None
        c.update()

    def _rolar(self, delta, orientacao):
        bar = self.scroll.verticalScrollBar() if orientacao == Qt.Vertical else self.scroll.horizontalScrollBar()
        bar.setValue(int(bar.value() - delta * bar.singleStep() / 120.0 * 3))

    def resizeEvent(self, ev):
        super(Checagem, self).resizeEvent(ev)
        self.ajustar()
