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

## Running

Depends on `ollama` to serve a running model.
Can run this by following the [instructions](https://docs.ollama.com/docker). The `--model` parameter is the model's name in the output of `ollama ls`. Default is `gemma4:e4b`, which is [7.2GB](https://ollama.com/library/gemma4).
The default assumes the model server is at `localhost:11434/api/generate` (the ollama default). It's also possible to use a remotely-hosted model by passing `--url`.

### Dependencies

To run `main.py`, we use `uv` for dependency management. 
Main dependencies are:
- `pdfplumber` to extract text from pdfs: `https://github.com/jsvine/pdfplumber`. 
- `pypdf` to concatenate pdfs: `https://github.com/py-pdf/pypdf`.
- `pytesseract` for OCR
- `rich` for pretty-printing to terminal

### Example

```
uv run main.py -m gemma4:e4b -o <my_trip.pdf> <folder>/*
```
