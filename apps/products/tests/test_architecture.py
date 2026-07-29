from pathlib import Path


def test_product_image_is_explicitly_deferred():
    models = Path("apps/products/models.py").read_text(encoding="utf-8")
    decision = Path("docs/decisions/ADR-007-DEFER-PRODUCT-IMAGE.md").read_text(encoding="utf-8")
    assert "class ProductImage" not in models
    assert "adiar productimage" in decision.lower()
