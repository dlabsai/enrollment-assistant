from io import BytesIO

from openpyxl import load_workbook

from app.api.excel_export import ExcelExportWorkbook


def test_excel_export_workbook_preserves_literal_string_values() -> None:
    values = ("- Markdown bullet", "=1+1")
    workbook = ExcelExportWorkbook(
        sheet_title="Literal text", headers=("Value",), column_widths=(24,)
    )
    for value in values:
        workbook.append((value,))

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    exported_workbook = load_workbook(buffer, data_only=True, read_only=True)
    worksheet = exported_workbook.active
    assert worksheet is not None
    assert list(worksheet.iter_rows(values_only=True)) == [
        ("Value",),
        ("- Markdown bullet",),
        ("=1+1",),
    ]
    exported_workbook.close()
