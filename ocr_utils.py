import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import pdfplumber

def extract_text_from_file(file_path: str) -> str:
    """
    Extracts text from a PDF or image using both digital extraction and OCR if necessary.
    """
    is_pdf = file_path.lower().endswith(".pdf")
    try:
        # First attempt: Use pdfplumber for digital text extraction if it's a PDF
        text = ""
        if is_pdf:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"

        # If text is empty or very short, or if it's an image, try OCR
        if len(text.strip()) < 100 or not is_pdf:
            print(f"Low text density or image detected in {file_path}, attempting OCR...")
            text = extract_text_from_pdf_or_images(file_path, is_pdf=is_pdf)

        return text
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
        # Fallback to OCR if initial attempt fails
        try:
            return extract_text_from_pdf_or_images(file_path, is_pdf=is_pdf)
        except Exception as ocr_e:
            print(f"OCR fallback also failed: {ocr_e}")
            return ""

def preprocess_image(image: Image.Image) -> Image.Image:
    """
    Preprocesses an image for better OCR accuracy.
    - Converts to grayscale.
    - Applies thresholding to make text sharper.
    """
    try:
        # Convert to grayscale
        gray_image = image.convert("L")

        # Apply a simple thresholding
        _, thresholded_image = gray_image.point(lambda x: 255 if x > 128 else 0)

        return thresholded_image
    except Exception as e:
        return image

def extract_text_from_pdf_or_images(source_path: str, is_pdf: bool = True) -> str:
    """
    Extracts text from either a PDF file or an image file using OCR.
    """
    images = []
    try:
        if is_pdf:
            # Convert PDF to list of PIL Images
            images = convert_from_path(source_path)
        else:
            # Open image file
            images = [Image.open(source_path)]

        extracted_text = []
        for img in images:
            # Pre-processing
            processed_img = preprocess_image(img)

            # Perform OCR
            text = pytesseract.image_to_string(processed_img)
            if text.strip():
                extracted_text.append(text.strip())

        return "\n".join(extracted_text)

    except Exception as e:
        logger.error(f"Error during OCR process for {source_path}: {e}")
        return ""
