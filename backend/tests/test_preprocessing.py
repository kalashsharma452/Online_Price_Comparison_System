import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from preprocessing import preprocess_image, preprocess_for_mobilenet, preprocess_for_efficientnet


class TestPreprocessing(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _save_image(self, image, filename, fmt):
        path = os.path.join(self.tmpdir.name, filename)
        image.save(path, format=fmt)
        return path

    def test_preprocess_jpeg_resize_and_normalize(self):
        image = Image.new("RGB", (640, 480), color=(120, 80, 200))
        path = self._save_image(image, "sample.jpg", "JPEG")

        output = preprocess_image(path, target_size=(224, 224))

        self.assertEqual(output.shape, (224, 224, 3))
        self.assertEqual(output.dtype, np.float32)
        self.assertGreaterEqual(output.min(), 0.0)
        self.assertLessEqual(output.max(), 1.0)

    def test_preprocess_grayscale_png_converts_to_rgb(self):
        image = Image.new("L", (120, 120), color=150)
        path = self._save_image(image, "gray.png", "PNG")

        output = preprocess_image(path, target_size=(224, 224))

        self.assertEqual(output.shape, (224, 224, 3))

    def test_preprocess_rgba_png_converts_to_rgb(self):
        image = Image.new("RGBA", (256, 256), color=(20, 90, 120, 100))
        path = self._save_image(image, "alpha.png", "PNG")

        output = preprocess_image(path, target_size=(224, 224))

        self.assertEqual(output.shape, (224, 224, 3))
        self.assertEqual(output.dtype, np.float32)

    def test_preprocess_webp_if_supported(self):
        image = Image.new("RGB", (180, 200), color=(210, 40, 80))
        path = os.path.join(self.tmpdir.name, "sample.webp")
        try:
            image.save(path, format="WEBP")
        except OSError:
            self.skipTest("WebP is not supported by this Pillow build")

        output = preprocess_image(path, target_size=(224, 224))
        self.assertEqual(output.shape, (224, 224, 3))

    def test_preprocess_handles_noisy_image(self):
        rng = np.random.default_rng(seed=7)
        noisy = rng.integers(0, 256, size=(300, 300, 3), dtype=np.uint8)
        image = Image.fromarray(noisy, mode="RGB")
        path = self._save_image(image, "noisy.png", "PNG")

        output = preprocess_image(path, target_size=(224, 224))
        self.assertEqual(output.shape, (224, 224, 3))
        self.assertGreater(float(output.std()), 0.0)

    def test_mobilenet_preprocess_output_shape_and_range(self):
        image = Image.new("RGB", (260, 190), color=(180, 120, 40))
        path = self._save_image(image, "mobilenet.jpg", "JPEG")

        output = preprocess_for_mobilenet(path, target_size=(224, 224))
        self.assertEqual(output.shape, (1, 224, 224, 3))
        self.assertEqual(output.dtype, np.float32)
        self.assertGreaterEqual(float(output.min()), -1.1)
        self.assertLessEqual(float(output.max()), 1.1)

    def test_efficientnet_preprocess_without_tta_shape(self):
        image = Image.new("RGB", (301, 199), color=(44, 100, 221))
        path = self._save_image(image, "efficientnet_no_tta.jpg", "JPEG")

        output = preprocess_for_efficientnet(path, target_size=(224, 224), use_tta=False)
        self.assertEqual(output.shape, (1, 224, 224, 3))
        self.assertEqual(output.dtype, np.float32)

    def test_efficientnet_preprocess_with_tta_shape(self):
        image = Image.new("RGB", (301, 199), color=(44, 100, 221))
        path = self._save_image(image, "efficientnet_tta.jpg", "JPEG")

        output = preprocess_for_efficientnet(path, target_size=(224, 224), use_tta=True)
        self.assertEqual(output.shape, (2, 224, 224, 3))
        self.assertEqual(output.dtype, np.float32)


if __name__ == "__main__":
    unittest.main()
