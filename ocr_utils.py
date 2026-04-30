import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import logging

logger = logging.getLogger(__name__)

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
        logger.error(f"Error preprocessing image: {e}")
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
