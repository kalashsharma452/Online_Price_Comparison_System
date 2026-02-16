import numpy as np
import tensorflow as tf
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def open_image_rgb(path):
    """Open any supported image format and normalize mode to RGB."""
    return Image.open(path).convert("RGB")


def resize_image(image, target_size=(224, 224)):
    return image.resize(target_size)


def resize_and_center_crop(image, target_size=(224, 224)):
    # Preserve aspect ratio, then crop center instead of stretching.
    return ImageOps.fit(image, target_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def reduce_noise(image, median_size=3, gaussian_radius=0.8):
    # Median removes impulse/salt-pepper noise, then Gaussian smooths fine grain.
    denoised = image.filter(ImageFilter.MedianFilter(size=median_size))
    denoised = denoised.filter(ImageFilter.GaussianBlur(radius=gaussian_radius))
    return denoised


def enhance_image(image, contrast_factor=1.15, brightness_factor=1.05):
    contrasted = ImageEnhance.Contrast(image).enhance(contrast_factor)
    brightened = ImageEnhance.Brightness(contrasted).enhance(brightness_factor)
    return brightened


def normalize_image(image):
    array = np.asarray(image).astype("float32") / 255.0
    return np.clip(array, 0.0, 1.0)


def preprocess_image(path, target_size=(224, 224)):
    """Enhanced pipeline for general cleanup/visual quality."""
    image = open_image_rgb(path)
    image = resize_image(image, target_size=target_size)
    image = reduce_noise(image)
    image = enhance_image(image)
    return normalize_image(image)


def prepare_model_input(normalized_image):
    # MobileNetV2 expects values in [-1, 1] after preprocess_input.
    pixel_space = normalized_image * 255.0
    mobilenet_ready = tf.keras.applications.mobilenet_v2.preprocess_input(pixel_space)
    return np.expand_dims(mobilenet_ready, axis=0)


def preprocess_for_mobilenet(path, target_size=(224, 224)):
    """
    Model-aligned inference pipeline.
    Keep transformations minimal to preserve the data distribution MobileNetV2 expects.
    """
    image = open_image_rgb(path)
    image = resize_and_center_crop(image, target_size=target_size)
    image_array = np.asarray(image).astype("float32")
    mobilenet_ready = tf.keras.applications.mobilenet_v2.preprocess_input(image_array)
    return np.expand_dims(mobilenet_ready, axis=0)


def preprocess_for_efficientnet(path, target_size=(224, 224), use_tta=True):
    """
    EfficientNet preprocessing with optional lightweight test-time augmentation.
    Returns a batch tensor shaped [N, H, W, 3].
    """
    image = open_image_rgb(path)
    image = resize_and_center_crop(image, target_size=target_size)

    variants = [image]
    if use_tta:
        variants.append(ImageOps.mirror(image))

    batch = []
    for variant in variants:
        image_array = np.asarray(variant).astype("float32")
        model_ready = tf.keras.applications.efficientnet.preprocess_input(image_array)
        batch.append(model_ready)

    return np.stack(batch, axis=0)
