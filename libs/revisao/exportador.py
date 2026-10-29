# -*- coding: utf-8 -*-
"""Gravação do dataset YOLO-seg (tiles aprovados) e do descarte (instâncias e tiles reprovados)."""
import json
import os
import shutil

from PyQt5.QtGui import QColor, QImage, QPainter

from libs.revisao.projeto import split_de

COR_CINZA = 114   # letterbox do YOLO: região coberta não ensina nada


def garantir_data_yaml(proj):
    arq = proj.p('dataset', 'data.yaml')
    if os.path.exists(arq) or not proj.classes:
        return
    # sem 'path': o ultralytics usa a pasta do próprio data.yaml
    linhas = ['train: images/train', 'val: images/val', 'names:']
    linhas += ['  %d: %s' % (i, c) for i, c in enumerate(proj.classes)]
    with open(arq, 'w', encoding='utf-8') as f:
        f.write('\n'.join(linhas) + '\n')


def exportar_tile(proj, tile, poligonos, cinza):
    """tile: dict do Lote. poligonos: [(classe, [(x, y), ...])] em px do tile. cinza: [(x0, y0, x1, y1)].

    Retorna (split, [arquivos gravados]) para o registro da decisão (desfazer apaga os arquivos).
    """
    split = split_de(tile['sequencia'])
    pi = proj.p('dataset', 'images', split)
    pl = proj.p('dataset', 'labels', split)
    for d in (pi, pl):
        if not os.path.isdir(d):
            os.makedirs(d)
    garantir_data_yaml(proj)
    arq_img = os.path.join(pi, tile['nome'] + '.jpg')
    arq_txt = os.path.join(pl, tile['nome'] + '.txt')
    if cinza:
        img = QImage(tile['caminho'])
        p = QPainter(img)
        for x0, y0, x1, y1 in cinza:
            p.fillRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0), QColor(COR_CINZA, COR_CINZA, COR_CINZA))
        p.end()
        if not img.save(arq_img + '.tmp.jpg', 'JPG', 95):
            raise IOError(u'falha ao gravar %s' % arq_img)
        os.replace(arq_img + '.tmp.jpg', arq_img)
    else:
        shutil.copyfile(tile['caminho'], arq_img + '.tmp')
        os.replace(arq_img + '.tmp', arq_img)
    W, H = float(tile['largura']), float(tile['altura'])
    linhas = []
    for classe, pts in poligonos:
        if len(pts) < 3 or classe not in proj.classes:
            continue
        xy = ' '.join('%.6f %.6f' % (min(max(x / W, 0.0), 1.0), min(max(y / H, 0.0), 1.0)) for x, y in pts)
        linhas.append('%d %s' % (proj.classes.index(classe), xy))
    with open(arq_txt + '.tmp', 'w', encoding='utf-8') as f:
        f.write('\n'.join(linhas) + ('\n' if linhas else ''))
    os.replace(arq_txt + '.tmp', arq_txt)
    return split, [arq_img, arq_txt]


def descartar_tile(proj, tile):
    pasta = proj.p('descarte', 'tiles')
    if not os.path.isdir(pasta):
        os.makedirs(pasta)
    destino = os.path.join(pasta, tile['nome'] + '.jpg')
    shutil.copyfile(tile['caminho'], destino)
    return [destino]


def descartar_instancias(proj, insts):
    """Copia a miniatura de cada instância reprovada para descarte/recortes/<classe>/ (negativos)."""
    arquivos = []
    for x in insts:
        pasta = proj.p('descarte', 'recortes', x['classe'])
        if not os.path.isdir(pasta):
            os.makedirs(pasta)
        destino = os.path.join(pasta, x['id'] + '.jpg')
        if os.path.exists(x['miniatura_abs']):
            shutil.copyfile(x['miniatura_abs'], destino)
            arquivos.append(destino)
    return arquivos


def criar_pedido(proj, lote, tile, caixa, classe, n):
    """Pede ao processador (PC com GPU) a máscara SAM de uma caixa desenhada pelo revisor."""
    pasta = proj.p('revisao', 'pedidos')
    if not os.path.isdir(pasta):
        os.makedirs(pasta)
    pid = '%s_p%02d' % (tile['nome'], n)
    arq = os.path.join(pasta, pid + '.json')
    with open(arq + '.tmp', 'w', encoding='utf-8') as f:
        json.dump({'id': pid, 'lote': lote, 'pano': tile['pano'], 'tile': tile['nome'],
                   'caixa': [round(v, 1) for v in caixa], 'classe': classe}, f, ensure_ascii=False)
    os.replace(arq + '.tmp', arq)
    return pid, arq


def remover(arquivos):
    for a in arquivos or []:
        try:
            os.remove(a)
        except OSError:
            pass
