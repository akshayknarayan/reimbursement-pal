Reimbursement Pal
-----------------

Process an input list of pdf receipts related to a reimbursement request.

### LLM-involved tasks:
- for each receipt, produce a short summary.
- for each receipt, extract the amount of reimbursement the receipt represents.

### PDF manipulation tasks:
- concatenate the receipts together.
- produce a cover page, with items for each receipt and a grand total.

## Structure

Use `uv` for dependency management. Dependencies should be:
- `pdfplumber` to extract text from pdfs: `https://github.com/jsvine/pdfplumber`. 
- `pypdf` to concatenate pdfs: `https://github.com/py-pdf/pypdf`.

## Version Control

Use `jj` for version control. `jj new` will checkpoint current changes.
