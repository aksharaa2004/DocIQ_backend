# DocIQ Python OCR backend

This FastAPI service uses English PP-OCRv6 by default to extract text from images embedded in documents. It can also be configured to use DeepSeek-OCR for image transcription with table markup.

The existing Node backend sends scanned PDF pages and embedded DOCX/PPTX images to this service when `OCR_PROVIDER=python` (the default). Searchable PDF text, DOCX text, and PPTX slide text continue through their existing extractors. The Node client posts each image as multipart field `image` and reads the service's JSON `success` and `text` fields. Set `PYTHON_OCR_URL` if the service runs somewhere other than `http://127.0.0.1:8000`; `PYTHON_OCR_TIMEOUT_MS` controls the per-image request timeout and defaults to `120000` milliseconds. To use the existing Groq image OCR path instead, set `OCR_PROVIDER=groq` in `backend/.env`.

## Requirements

- Python 3.10 or newer
- Internet access the first time the service starts so PaddleOCR can download its English recognition and detection models
- Several GB of free disk space for packages and model cache

PP-OCRv6 runs on CPU by default and does not require CUDA. PaddlePaddle and PaddleOCR are installed from `requirements.txt`. The optional DeepSeek-OCR engine is considerably heavier; it requires a compatible PyTorch install and typically an NVIDIA GPU with substantial VRAM.

```powershell
cd backend/python_ocr
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uvicorn main:app --host 0.0.0.0 --port 8000
```

To configure an NVIDIA GPU for PaddleOCR, set `PADDLEOCR_DEVICE=gpu:0` and install a PaddlePaddle GPU build compatible with your CUDA environment. To select DeepSeek-OCR, first install the matching PyTorch build from [PyTorch Get Started](https://pytorch.org/get-started/locally/), then install `requirements-deepseek.txt` and set `OCR_ENGINE=deepseek`.

`OCR_LOAD_MODEL=false` lets the API start without loading model weights, for checking the health endpoint. `GET /health` reports the engine, language, and whether its model loaded.

## API

- `GET /health` reports whether the configured model loaded.
- `POST /api/ocr/table` accepts one multipart image under the field name `image` (JPEG, PNG, WEBP, TIFF, BMP, or GIF). It returns the recognized text, any parsed table markup, and image dimensions.
- `GET /docs` provides interactive API documentation.

Run this service in one terminal, then start the Node backend in a second terminal. Both processes must be running when documents containing embedded images are processed. In `backend/.env`, set `OCR_PROVIDER=python` and `PYTHON_OCR_URL=http://127.0.0.1:8000` (these are also the Node backend defaults); restart Node after changing its environment file.

PP-OCRv6 recognizes text and returns it in approximate reading order. It does not reconstruct table cells as HTML; choose `OCR_ENGINE=deepseek` when table markup from image OCR is required. Low-resolution, skewed, handwritten, or visually ambiguous images can still be misread, so review extracted content against the original image.

Example:

```powershell
curl.exe -X POST http://localhost:8000/api/ocr/table -F "image=@C:\path\to\image.png"
```
