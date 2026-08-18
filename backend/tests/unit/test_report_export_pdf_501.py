"""报告导出 format=pdf 抛 FormatNotImplementedError。

离线单测，不走 TestClient（路由层结构化 501 由 code review / 手动验证）。
"""
from __future__ import annotations

import pytest

from app.services.reports.exporter import export, FormatNotImplementedError


def test_export_pdf_raises_format_not_implemented():
    with pytest.raises(FormatNotImplementedError) as ei:
        export("# hi", "pdf")
    assert ei.value.fmt == "pdf"
