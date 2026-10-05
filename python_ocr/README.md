# DocIQ Python OCR backend

This standalone FastAPI service follows the DeepSeek-OCR approach used by [deepseek_ocr_app](https://github.com/rdumasia303/deepseek_ocr_app): load the model once, use dynamic image cropping, and retain table markup instead of flattening it into plain text.

The existing Node backend sends embedded DOCX/PPTX/PDF images to this service when `OCR_PROVIDER=python` (the default). Set `PYTHON_OCR_URL` if the service runs somewhere other than `http://127.0.0.1:8000`. To keep using the existing Groq image OCR path, set `OCR_PROVIDER=groq` in `backend/.env` instead.

## Requirements

- Python 3.10 or newer
- NVIDIA GPU with CUDA and enough VRAM for the selected model (the referenced app recommends 8–12 GB or more)
- Several GB of free disk space for model weights and cache

The model dependency is substantial. Install the PyTorch build that matches your CUDA setup using the instructions at [PyTorch Get Started](https://pytorch.org/get-started/locally/), then install the remaining requirements:

```powershell
cd backend/python_ocr
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn main:app --host 0.0.0.0 --port 8000
```

On a CPU-only machine, set `OCR_DEVICE=cpu` in `.env`. Inference will be substantially slower and model support/performance depends on the installed PyTorch build. `OCR_LOAD_MODEL=false` lets the API start without loading weights, for checking the health endpoint.

## API

- `GET /health` reports whether the model loaded.
- `POST /api/ocr/table` accepts one multipart image under the field name `image` (JPEG, PNG, WEBP, TIFF, BMP, or GIF). It responds with the full transcription, table HTML, parsed cell text and spans, and image dimensions.
- `GET /docs` provides interactive API documentation.

Run this service in one terminal, then start the existing Node backend in a second terminal. Both processes must be running when documents containing embedded images are processed. In `backend/.env`, set `OCR_PROVIDER=python` and `PYTHON_OCR_URL=http://127.0.0.1:8000` (these are also the Node backend defaults); restart Node after changing its environment file.

Example:

```powershell
curl.exe -X POST http://localhost:8000/api/ocr/table -F "image=@C:\path\to\table.png"
```

The model can misread low-resolution, skewed, handwritten, or visually ambiguous tables. Keep the original image and review extracted cells before using the result as authoritative data.
