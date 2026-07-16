from pathlib import Path

from PIL import Image, features
import pytest

from src.application.image_io import ExportImage
from src.domain.image import ImageFileFormat, ImageLimits, ImageValidationError
from src.infrastructure.pillow_image_codec import PillowImageCodec


def test_load_normalizes_exif_orientation(tmp_path: Path) -> None:
    source = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (80, 96), "navy")
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)
    document = PillowImageCodec().load(source, ImageLimits())
    assert (document.asset.width, document.asset.height) == (96, 80)
    assert document.asset.orientation_applied
    assert document.mode == "RGB"


def test_load_preserves_png_alpha_and_rejects_fake_extension(tmp_path: Path) -> None:
    codec = PillowImageCodec()
    source = tmp_path / "alpha.png"
    Image.new("RGBA", (80, 80), (20, 40, 60, 0)).save(source)
    document = codec.load(source, ImageLimits())
    assert document.mode == "RGBA"
    assert document.asset.has_alpha

    fake = tmp_path / "fake.jpg"
    Image.new("RGB", (80, 80), "red").save(fake, format="PNG")
    with pytest.raises(ImageValidationError) as error:
        codec.load(fake, ImageLimits())
    assert error.value.code == "extension_content_mismatch"


def test_load_rejects_corrupt_and_file_over_limit(tmp_path: Path) -> None:
    codec = PillowImageCodec()
    corrupt = tmp_path / "broken.png"
    corrupt.write_bytes(b"not-an-image")
    with pytest.raises(ImageValidationError) as invalid:
        codec.load(corrupt, ImageLimits())
    assert invalid.value.code == "invalid_image"

    valid = tmp_path / "valid.png"
    Image.new("RGB", (80, 80), "red").save(valid)
    with pytest.raises(ImageValidationError) as oversized:
        codec.load(valid, ImageLimits(max_bytes=valid.stat().st_size - 1))
    assert oversized.value.code == "file_too_large"


@pytest.mark.skipif(not features.check("webp"), reason="Pillow WebP codec unavailable")
def test_input_webp_is_supported(tmp_path: Path) -> None:
    source = tmp_path / "input.webp"
    Image.new("RGB", (96, 72), "green").save(source, format="WEBP", lossless=True)
    document = PillowImageCodec().load(source, ImageLimits())
    assert document.asset.file_format is ImageFileFormat.WEBP
    assert (document.asset.width, document.asset.height) == (96, 72)


@pytest.mark.skipif(not features.check("webp"), reason="Pillow WebP codec unavailable")
def test_export_all_five_formats_as_single_images(tmp_path: Path) -> None:
    source = tmp_path / "alpha.png"
    image = Image.new("RGBA", (96, 72), (20, 40, 60, 255))
    image.putpixel((0, 0), (200, 10, 30, 0))
    image.save(source)
    codec = PillowImageCodec()
    document = codec.load(source, ImageLimits())
    exporter = ExportImage(codec)
    outputs = [
        tmp_path / "result.jpg",
        tmp_path / "result.png",
        tmp_path / "result.webp",
        tmp_path / "result.gif",
        tmp_path / "result.tiff",
    ]
    for target in outputs:
        assert exporter.execute(document, target) == target
        with Image.open(target) as reopened:
            reopened.load()
            assert reopened.size == (96, 72)
            assert getattr(reopened, "n_frames", 1) == 1

    with Image.open(outputs[0]) as jpeg:
        red, green, blue = jpeg.convert("RGB").getpixel((0, 0))
        assert min(red, green, blue) > 240
    with Image.open(outputs[1]) as png:
        assert png.convert("RGBA").getpixel((0, 0))[3] == 0
    with Image.open(outputs[2]) as webp:
        assert webp.convert("RGBA").getpixel((0, 0))[3] == 0
    with Image.open(outputs[3]) as gif:
        assert min(gif.convert("RGB").getpixel((0, 0))) > 240


def test_export_refuses_to_overwrite_imported_source(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 80), "blue").save(source)
    codec = PillowImageCodec()
    document = codec.load(source, ImageLimits())
    with pytest.raises(ImageValidationError) as error:
        ExportImage(codec).execute(document, source)
    assert error.value.code == "source_overwrite"
