Reimbursement Pal
-----------------

Process an input list of pdf receipts related to a reimbursement request.

### LLM-involved tasks:
- for each receipt, include its date
- for each receipt, produce a short summary.
- for each receipt, extract the amount of reimbursement the receipt represents.

### PDF manipulation tasks:
- produce a cover page, with items for each receipt and a grand total.
- concatenate the receipts together.

### Example

```
uv run main.py -m gemma4:e4b -o <my_trip.pdf> <folder>/*
```

## Structure

Use `uv` for dependency management. Dependencies should be:
- `pdfplumber` to extract text from pdfs: `https://github.com/jsvine/pdfplumber`. 
- `pypdf` to concatenate pdfs: `https://github.com/py-pdf/pypdf`.
- `pytesseract` for OCR
- `rich` for pretty-printing to terminal

## Version Control

Use `jj` for version control. `jj new` will checkpoint current changes.
