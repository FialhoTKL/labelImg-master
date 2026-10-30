# -*- coding: utf-8 -*-
"""Estado da revisão: lotes prontos (do processador) + decisões do revisor (revisao/decisoes.jsonl).

decisoes.jsonl é append-only e é o checkpoint: cada ação vira uma linha gravada na hora
(flush + fsync). Ao abrir, o estado é refeito relendo o arquivo. Registros:

  instancia            {id, lote, tile, classe_orig, classe, decisao: aprovar|reprovar, pre, conf, origem}
  desfazer_instancias  {ids}
  tile                 {lote, tile, estado: completo|descartado|aguardando, split, poligonos, cinza, arquivos}
                       aguardando = o revisor pediu à GPU a máscara de caixas desenhadas (pedidos)
  desfazer_tile        {tile}
  lote                 {lote, estado: concluido}
"""
import getpass
import hashlib
import json
import os
import time

FRAC_VAL = 0.20       # fração de SEQUÊNCIAS na validação (split por sequência, sem vazamento)
FRAC_FUNDO = 0.05     # fração de tiles sem nenhuma instância aprovada que entram como fundo


def _ler_json(arq, padrao=None):
    if not os.path.exists(arq):
        return padrao
    with open(arq, encoding='utf-8') as f:
        return json.load(f)


def _hash01(texto):
    return int(hashlib.md5(texto.encode('utf-8')).hexdigest()[:8], 16) / 0xFFFFFFFF


def split_de(sequencia):
    return 'val' if _hash01('split|' + sequencia) < FRAC_VAL else 'train'


class Lote(object):
    """Um lote fechado pelo processador: tiles e instâncias, com a pontuação mais recente."""

    def __init__(self, proj, nome):
        self.proj = proj
        self.nome = nome
        pasta = proj.p('processado', nome)
        info = _ler_json(os.path.join(pasta, 'lote.json'), {})
        self.classes = info.get('classes', proj.classes)
        self.tiles = []
        self.inst = {}
        for pano in info.get('panoramas', []):
            d = _ler_json(os.path.join(pasta, pano, 'instancias.json'))
            if not d or d.get('duplicata'):
                continue
            for t in d['tiles']:
                tile = dict(t, pano=pano, sequencia=d.get('sequencia', pano),
                            caminho=os.path.join(pasta, pano, t['arquivo']))
                for x in t['instancias']:
                    x.update(tile=t['nome'], lote=nome, pano=pano,
                             miniatura_abs=os.path.join(pasta, pano, x['miniatura']))
                    self.inst[x['id']] = x
                tile['ids'] = [x['id'] for x in t['instancias']]
                del tile['instancias']
                self.tiles.append(tile)
        self._aplicar_pontuacao(pasta)
        self.tile_por_nome = {t['nome']: t for t in self.tiles}

    def _aplicar_pontuacao(self, pasta):
        """pontuacao_vN.json (etapa aprender do processador) atualiza conf/pré-decisão."""
        vs = sorted(f for f in os.listdir(pasta) if f.startswith('pontuacao_v') and f.endswith('.json'))
        if not vs:
            return
        for i, v in _ler_json(os.path.join(pasta, vs[-1]), {}).items():
            if i in self.inst:
                self.inst[i].update(v)

    # --- etapa 1: grade -------------------------------------------------
    def pendentes(self, classe=None):
        """Instâncias sem decisão, maior confiança primeiro."""
        xs = [x for i, x in self.inst.items() if i not in self.proj.dec and (classe is None or x['classe'] == classe)]
        return sorted(xs, key=lambda x: -x['conf'])

    def classes_pendentes(self):
        cs = {x['classe'] for i, x in self.inst.items() if i not in self.proj.dec}
        return [c for c in self.classes if c in cs]

    # --- etapa 2: checagem do tile -------------------------------------
    def aprovadas(self, tile):
        """[(instância, classe final)] aprovadas na grade para o tile."""
        out = []
        for i in self.tile_por_nome[tile]['ids']:
            d = self.proj.dec.get(i)
            if d and d['decisao'] == 'aprovar':
                out.append((self.inst[i], d['classe']))
        return out

    def precisa_checar(self, tile):
        return bool(self.aprovadas(tile)) or _hash01('fundo|' + tile) < FRAC_FUNDO

    def resposta(self, pedido_id):
        """Polígono devolvido pelo processador para um pedido (caixa -> SAM), ou None se ainda não chegou."""
        return _ler_json(self.proj.p('processado', self.nome, 'pedidos_resp', pedido_id + '.json'))

    def _estado_tile(self, nome):
        return self.proj.tiles.get(nome, {}).get('estado')

    def pronto(self, nome):
        r = self.proj.tiles.get(nome)
        return bool(r) and r['estado'] == 'aguardando' and \
            all(os.path.exists(self.proj.p('processado', self.nome, 'pedidos_resp', i + '.json')) for i in r['pedidos'])

    def tiles_pendentes(self):
        novos = [t for t in self.tiles if t['nome'] not in self.proj.tiles and self.precisa_checar(t['nome'])]
        return novos + [t for t in self.tiles if self.pronto(t['nome'])]

    def aguardando(self):
        return [t for t in self.tiles if self._estado_tile(t['nome']) == 'aguardando' and not self.pronto(t['nome'])]

    def etapa(self):
        if self.pendentes():
            return 'grade'
        if self.tiles_pendentes():
            return 'checagem'
        if self.aguardando():
            return 'aguardando'
        return 'concluido'

    def progresso(self):
        n_i = len(self.inst)
        d_i = sum(1 for i in self.inst if i in self.proj.dec)
        chk = [t for t in self.tiles if self.precisa_checar(t['nome'])] if d_i == n_i else []
        d_t = sum(1 for t in chk if self._estado_tile(t['nome']) in ('completo', 'descartado'))
        return {'instancias': (d_i, n_i), 'tiles': (d_t, len(chk))}


class ProjetoRevisao(object):
    def __init__(self, raiz):
        self.raiz = os.path.abspath(raiz)
        if not os.path.exists(self.p('processado', 'indice.json')):
            raise IOError(u'Pasta sem projeto do processador (falta processado/indice.json): %s' % raiz)
        for d in ('revisao', 'dataset', 'descarte'):
            if not os.path.isdir(self.p(d)):
                os.makedirs(self.p(d))
        self.revisor = getpass.getuser()
        self.arq_dec = self.p('revisao', 'decisoes.jsonl')
        self.dec = {}          # id -> último registro 'instancia'
        self.tiles = {}        # tile -> registro 'tile'
        self.estado_lote = {}  # lote -> estado
        self.historico = []    # (t, decisao, classe_orig) para métricas
        self.classes = []
        self._reler()
        for l in self.lotes():
            if l['fechado']:
                self.classes = _ler_json(self.p('processado', l['nome'], 'lote.json'), {}).get('classes', [])
                break

    def p(self, *partes):
        return os.path.join(self.raiz, *partes)

    # --- decisões ----------------------------------------------------------
    def _reler(self):
        if not os.path.exists(self.arq_dec):
            return
        with open(self.arq_dec, encoding='utf-8') as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    self._aplicar(json.loads(linha))
                except ValueError:
                    pass      # última linha cortada por queda de energia: ignorada

    def _aplicar(self, r):
        tipo = r.get('tipo')
        if tipo == 'instancia':
            self.dec[r['id']] = r
            self.historico.append((r.get('t', 0), r['decisao'], r.get('classe_orig')))
        elif tipo == 'desfazer_instancias':
            for i in r['ids']:
                self.dec.pop(i, None)
        elif tipo == 'tile':
            self.tiles[r['tile']] = r
        elif tipo == 'desfazer_tile':
            self.tiles.pop(r['tile'], None)
        elif tipo == 'lote':
            self.estado_lote[r['lote']] = r['estado']

    def registrar(self, registros):
        """Grava e aplica uma lista de registros de uma vez (uma página da grade = uma chamada)."""
        agora = time.time()
        linhas = []
        for r in registros:
            r = dict(r, t=agora, rev=self.revisor)
            linhas.append(json.dumps(r, ensure_ascii=False))
            self._aplicar(r)
        with open(self.arq_dec, 'a', encoding='utf-8') as f:
            f.write('\n'.join(linhas) + '\n')
            f.flush()
            os.fsync(f.fileno())

    # --- lotes ---------------------------------------------------------------
    # Projetos grandes têm milhares de lotes numa pasta de rede: cada consulta ao disco custa caro.
    # Um lote fechado (lote.json gravado) não muda mais, então fica em cache; e como o processador
    # fecha os lotes em ordem, a busca para depois de alguns lotes seguidos ainda abertos.
    ABERTOS_A_CONFERIR = 10

    def _indice(self):
        arq = self.p('processado', 'indice.json')
        st = os.stat(arq)
        chave = (st.st_mtime, st.st_size)
        if getattr(self, '_idx', None) is None or self._idx[0] != chave:
            self._idx = (chave, _ler_json(arq, {'lotes': []})['lotes'])
        return self._idx[1]

    def lotes(self):
        if not hasattr(self, '_fechados'):
            self._fechados = set()
        out = []
        abertos = 0
        for l in self._indice():
            nome = l['nome']
            if nome not in self._fechados and abertos < self.ABERTOS_A_CONFERIR:
                if os.path.exists(self.p('processado', nome, 'lote.json')):
                    self._fechados.add(nome)
                else:
                    abertos += 1
            out.append({'nome': nome, 'n_panoramas': len(l['panoramas']), 'fechado': nome in self._fechados,
                        'estado': self.estado_lote.get(nome)})
        return out

    def info_lote(self, nome):
        """lote.json (imutável depois de gravado), em cache."""
        if not hasattr(self, '_info'):
            self._info = {}
        if nome not in self._info:
            self._info[nome] = _ler_json(self.p('processado', nome, 'lote.json'), {})
        return self._info[nome]

    def lote(self, nome):
        return Lote(self, nome)

    # --- métricas -------------------------------------------------------------
    def metricas(self, janela_s=3600):
        agora = time.time()
        recentes = [d for d in self.dec.values() if agora - d.get('t', 0) <= janela_s]
        por_classe = {}
        for i, d in self.dec.items():
            c = por_classe.setdefault(d.get('classe_orig') or d['classe'], {'aprovar': 0, 'reprovar': 0})
            c[d['decisao']] += 1
        return {'ultima_hora': len(recentes), 'por_classe': por_classe, 'total': len(self.dec),
                'tiles': sum(1 for r in self.tiles.values() if r['estado'] == 'completo')}
