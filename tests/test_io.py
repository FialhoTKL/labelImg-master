import os
import sys
import unittest

class TestPascalVocRW(unittest.TestCase):

    def test_upper(self):
        dir_name = os.path.abspath(os.path.dirname(__file__))
        libs_path = os.path.join(dir_name, '..', 'libs')
        sys.path.insert(0, libs_path)
        from pascal_voc_io import PascalVocWriter
        from pascal_voc_io import PascalVocReader

        # Test Write/Read
        writer = PascalVocWriter('tests', 'test', (512, 512, 1), local_img_path='tests/test.512.512.bmp')
        difficult = 1
        writer.add_bnd_box(60, 40, 430, 504, 'person', difficult)
        writer.add_bnd_box(113, 40, 450, 403, 'face', difficult)
        writer.save('tests/test.xml')

        reader = PascalVocReader('tests/test.xml')
        shapes = reader.get_shapes()

        person_bnd_box = shapes[0]
        face = shapes[1]
        self.assertEqual(person_bnd_box[0], 'person')
        self.assertEqual(person_bnd_box[1], [(60, 40), (430, 40), (430, 504), (60, 504)])
        self.assertEqual(face[0], 'face')
        self.assertEqual(face[1], [(113, 40), (450, 40), (450, 403), (113, 403)])


class TestCreateMLRW(unittest.TestCase):

    def test_a_write(self):
        dir_name = os.path.abspath(os.path.dirname(__file__))
        libs_path = os.path.join(dir_name, '..', 'libs')
        sys.path.insert(0, libs_path)
        from create_ml_io import CreateMLWriter

        person = {'label': 'person', 'points': ((65, 45), (420, 45), (420, 512), (65, 512))}
        face = {'label': 'face', 'points': ((245, 250), (350, 250), (350, 365), (245, 365))}

        expected_width = 105    # 350-245 -> create_ml_io.py ll 46
        expected_height = 115   # 365-250 -> create_ml_io.py ll 49
        expected_x = 297.5      # 245+105/2 -> create_ml_io.py ll 53
        expected_y = 307.5      # 250+115/2 > create_ml_io.py ll 54

        shapes = [person, face]
        output_file = dir_name + "/tests.json"

        writer = CreateMLWriter('tests', 'test.512.512.bmp', (512, 512, 1), shapes, output_file,
                                local_img_path='tests/test.512.512.bmp')
        
        writer.verified = True
        writer.write()

        # check written json
        with open(output_file, "r") as file:
            input_data = file.read()

        import json
        data_dict = json.loads(input_data)[0]
        self.assertEqual(True, data_dict['verified'], 'verified tag not reflected')
        self.assertEqual('test.512.512.bmp', data_dict['image'], 'filename not correct in .json')
        self.assertEqual(2, len(data_dict['annotations']), 'output file contains to less annotations')
        face = data_dict['annotations'][1]
        self.assertEqual('face', face['label'], 'label name is wrong')
        face_coords = face['coordinates']
        self.assertEqual(expected_width, face_coords['width'], 'calculated width is wrong')
        self.assertEqual(expected_height, face_coords['height'], 'calculated height is wrong')
        self.assertEqual(expected_x, face_coords['x'], 'calculated x is wrong')
        self.assertEqual(expected_y, face_coords['y'], 'calculated y is wrong')

    def test_b_read(self):
        dir_name = os.path.abspath(os.path.dirname(__file__))
        libs_path = os.path.join(dir_name, '..', 'libs')
        sys.path.insert(0, libs_path)
        from create_ml_io import CreateMLReader

        output_file = dir_name + "/tests.json"
        reader = CreateMLReader(output_file, 'tests/test.512.512.bmp')
        shapes = reader.get_shapes()
        face = shapes[1]

        self.assertEqual(2, len(shapes), 'shape count is wrong')
        self.assertEqual('face', face[0], 'label is wrong')

        face_coords = face[1]
        x_min = face_coords[0][0]
        x_max = face_coords[1][0]
        y_min = face_coords[0][1]
        y_max = face_coords[2][1]

        self.assertEqual(245, x_min, 'xmin is wrong')
        self.assertEqual(350, x_max, 'xmax is wrong')
        self.assertEqual(250, y_min, 'ymin is wrong')
        self.assertEqual(365, y_max, 'ymax is wrong')


class TestYoloSegRW(unittest.TestCase):

    def test_polygon_round_trip(self):
        dir_name = os.path.abspath(os.path.dirname(__file__))
        sys.path.insert(0, os.path.join(dir_name, '..', 'libs'))
        from yolo_io import YOLOWriter, YoloReader

        class Img:  # o leitor só usa tamanho e escala de cinza
            def width(self): return 512
            def height(self): return 256
            def isGrayscale(self): return False

        out = os.path.join(dir_name, 'seg_test.txt')
        writer = YOLOWriter('tests', 'seg_test', (256, 512, 3))
        writer.add_polygon([(10, 20), (100, 20), (60, 200)], 'poste', 0)
        writer.add_bnd_box(200, 50, 300, 150, 'placa', 0)   # vira polígono de 4 cantos
        writer.save(class_list=['poste', 'placa'], target_file=out)

        with open(out) as f:
            linhas = f.read().split('\n')
        self.assertEqual(linhas[0], '0 0.019531 0.078125 0.195312 0.078125 0.117188 0.781250')
        self.assertEqual(len(linhas[1].split()), 9)

        shapes = YoloReader(out, Img()).get_shapes()
        self.assertEqual(shapes[0][0], 'poste')
        self.assertEqual(shapes[0][5], 'polygon')
        for (x, y), (ex, ey) in zip(shapes[0][1], [(10, 20), (100, 20), (60, 200)]):
            self.assertAlmostEqual(x, ex, places=2)
            self.assertAlmostEqual(y, ey, places=2)
        self.assertEqual([tuple(round(v) for v in p) for p in shapes[1][1]],
                         [(200, 50), (300, 50), (300, 150), (200, 150)])
        os.remove(out)
        os.remove(os.path.join(dir_name, 'classes.txt'))


if __name__ == '__main__':
    unittest.main()
