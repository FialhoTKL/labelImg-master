#!/usr/bin/env python
# -*- coding: utf8 -*-
import codecs
import os

from libs.constants import DEFAULT_ENCODING

TXT_EXT = '.txt'
ENCODE_METHOD = DEFAULT_ENCODING


def read_classes_file(path):
    """Read classes.txt. Older versions wrote it in the Windows ANSI code page
    (cp1252) instead of UTF-8, so accented class names (e.g. "ç") failed to
    decode; fall back to cp1252 for those files. They are rewritten as UTF-8
    on the next save."""
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        text = raw.decode(ENCODE_METHOD)
    except UnicodeDecodeError:
        text = raw.decode('cp1252', errors='replace')
    return text.lstrip(u'\ufeff').replace('\r\n', '\n').strip('\n').split('\n')

class YOLOWriter:

    def __init__(self, folder_name, filename, img_size, database_src='Unknown', local_img_path=None):
        self.folder_name = folder_name
        self.filename = filename
        self.database_src = database_src
        self.img_size = img_size
        self.box_list = []
        self.local_img_path = local_img_path
        self.verified = False

    def add_bnd_box(self, x_min, y_min, x_max, y_max, name, difficult):
        bnd_box = {'xmin': x_min, 'ymin': y_min, 'xmax': x_max, 'ymax': y_max}
        bnd_box['name'] = name
        bnd_box['difficult'] = difficult
        self.box_list.append(bnd_box)

    def add_polygon(self, points, name, difficult):
        """Polígono em pixels [(x, y), ...] -> linha YOLO-seg."""
        x_min, y_min = min(p[0] for p in points), min(p[1] for p in points)
        x_max, y_max = max(p[0] for p in points), max(p[1] for p in points)
        self.box_list.append({'xmin': x_min, 'ymin': y_min, 'xmax': x_max, 'ymax': y_max,
                              'name': name, 'difficult': difficult, 'points': list(points)})

    def has_polygons(self):
        return any('points' in b for b in self.box_list)

    def polygon_to_yolo_line(self, box, class_list):
        """YOLO-seg: classe x1 y1 x2 y2 ... normalizados. Caixa vira o polígono dos 4 cantos."""
        if box['name'] not in class_list:
            class_list.append(box['name'])
        pts = box.get('points') or [(box['xmin'], box['ymin']), (box['xmax'], box['ymin']),
                                    (box['xmax'], box['ymax']), (box['xmin'], box['ymax'])]
        w, h = float(self.img_size[1]), float(self.img_size[0])
        coords = ' '.join('%.6f %.6f' % (min(max(x / w, 0.0), 1.0), min(max(y / h, 0.0), 1.0)) for x, y in pts)
        return '%d %s' % (class_list.index(box['name']), coords)

    def bnd_box_to_yolo_line(self, box, class_list=[]):
        x_min = box['xmin']
        x_max = box['xmax']
        y_min = box['ymin']
        y_max = box['ymax']

        x_center = float((x_min + x_max)) / 2 / self.img_size[1]
        y_center = float((y_min + y_max)) / 2 / self.img_size[0]

        w = float((x_max - x_min)) / self.img_size[1]
        h = float((y_max - y_min)) / self.img_size[0]

        # PR387
        box_name = box['name']
        if box_name not in class_list:
            class_list.append(box_name)

        class_index = class_list.index(box_name)

        return class_index, x_center, y_center, w, h

    def save(self, class_list=[], target_file=None):

        out_file = None  # Update yolo .txt
        out_class_file = None   # Update class list .txt

        if target_file is None:
            out_file = open(
            self.filename + TXT_EXT, 'w', encoding=ENCODE_METHOD)
            classes_file = os.path.join(os.path.dirname(os.path.abspath(self.filename)), "classes.txt")
            out_class_file = open(classes_file, 'w', encoding=ENCODE_METHOD)

        else:
            out_file = codecs.open(target_file, 'w', encoding=ENCODE_METHOD)
            classes_file = os.path.join(os.path.dirname(os.path.abspath(target_file)), "classes.txt")
            out_class_file = open(classes_file, 'w', encoding=ENCODE_METHOD)


        # Com algum polígono o arquivo inteiro sai em YOLO-seg (o ultralytics não aceita misturar).
        segment = self.has_polygons()
        for box in self.box_list:
            if segment:
                out_file.write(self.polygon_to_yolo_line(box, class_list) + '\n')
                continue
            class_index, x_center, y_center, w, h = self.bnd_box_to_yolo_line(box, class_list)
            out_file.write("%d %.6f %.6f %.6f %.6f\n" % (class_index, x_center, y_center, w, h))

        # print (classList)
        # print (out_class_file)
        for c in class_list:
            out_class_file.write(c+'\n')

        out_class_file.close()
        out_file.close()



class YoloReader:

    def __init__(self, file_path, image, class_list_path=None):
        # shapes type:
        # [labbel, [(x1,y1), (x2,y2), (x3,y3), (x4,y4)], color, color, difficult]
        self.shapes = []
        self.file_path = file_path

        if class_list_path is None:
            dir_path = os.path.dirname(os.path.realpath(self.file_path))
            self.class_list_path = os.path.join(dir_path, "classes.txt")
        else:
            self.class_list_path = class_list_path

        # print (file_path, self.class_list_path)

        self.classes = read_classes_file(self.class_list_path)

        # print (self.classes)

        img_size = [image.height(), image.width(),
                    1 if image.isGrayscale() else 3]

        self.img_size = img_size

        self.verified = False
        # try:
        self.parse_yolo_format()
        # except:
        #     pass

    def get_shapes(self):
        return self.shapes

    def add_shape(self, label, x_min, y_min, x_max, y_max, difficult):

        points = [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]
        self.shapes.append((label, points, None, None, difficult))

    def yolo_line_to_shape(self, class_index, x_center, y_center, w, h):
        label = self.classes[int(class_index)]

        x_min = max(float(x_center) - float(w) / 2, 0)
        x_max = min(float(x_center) + float(w) / 2, 1)
        y_min = max(float(y_center) - float(h) / 2, 0)
        y_max = min(float(y_center) + float(h) / 2, 1)

        x_min = round(self.img_size[1] * x_min)
        x_max = round(self.img_size[1] * x_max)
        y_min = round(self.img_size[0] * y_min)
        y_max = round(self.img_size[0] * y_max)

        return label, x_min, y_min, x_max, y_max

    def parse_yolo_format(self):
        with open(self.file_path, 'r', encoding=ENCODE_METHOD) as bnd_box_file:
            for line in bnd_box_file:
                values = line.split()
                if len(values) == 5:
                    class_index, x_center, y_center, w, h = values
                    label, x_min, y_min, x_max, y_max = self.yolo_line_to_shape(class_index, x_center, y_center, w, h)
                    # Caveat: difficult flag is discarded when saved as yolo format.
                    self.add_shape(label, x_min, y_min, x_max, y_max, False)
                elif len(values) >= 7 and len(values) % 2 == 1:
                    # YOLO-seg: classe + pares x y normalizados
                    label = self.classes[int(values[0])]
                    xy = [float(v) for v in values[1:]]
                    points = [(xy[i] * self.img_size[1], xy[i + 1] * self.img_size[0]) for i in range(0, len(xy), 2)]
                    self.shapes.append((label, points, None, None, False, 'polygon'))
