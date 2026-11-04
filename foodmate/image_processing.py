"""Validate, orient, and compact user photos before model requests."""

from __future__ import annotations

from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener


register_heif_opener()


class ImageInputError(ValueError):
    """A safe, user-displayable image validation error."""


def prepare_food_image(image_bytes: bytes, *, max_edge: int = 1920) -> bytes:
    """Return an EXIF-corrected, RGB JPEG suitable for upload to a vision API."""
    if not image_bytes:
        raise ImageInputError("没有收到图片内容，请重新选择照片。")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes)) as source:
                # Ask JPEG decoders to downsample during decode where supported,
                # then resize before making additional RGB/RGBA copies.
                source.draft("RGB", (max_edge, max_edge))
                source.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                oriented = ImageOps.exif_transpose(source)
                if "A" in oriented.getbands():
                    foreground = oriented.convert("RGBA")
                    background = Image.new("RGBA", foreground.size, "white")
                    background.alpha_composite(foreground)
                    image = background.convert("RGB")
                else:
                    image = oriented.convert("RGB")

                output = BytesIO()
                image.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
                return output.getvalue()
    except Image.DecompressionBombError:
        raise ImageInputError("这张图片分辨率过高，无法安全处理；请截取或压缩后重试。") from None
    except Image.DecompressionBombWarning:
        raise ImageInputError("这张图片分辨率过高，无法安全处理；请截取或压缩后重试。") from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImageInputError("无法读取这张图片。请重新导出为 JPG、PNG、WebP、AVIF 或 HEIC 后重试。") from None

