import pytest

from src.domain.product import ProductInfo


def test_product_info_requires_non_empty_identity() -> None:
    product = ProductInfo(name="图片翻译", version="0.1.0", milestone="M1")
    assert product.name == "图片翻译"
    with pytest.raises(ValueError, match="name"):
        ProductInfo(name=" ", version="0.1.0", milestone="M1")
