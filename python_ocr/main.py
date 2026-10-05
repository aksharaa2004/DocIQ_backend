"""FastAPI service for image OCR and table extraction with DeepSeek-OCR."""

from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-OCR")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
BASE_SIZE = int(os.getenv("BASE_SIZE", "1024"))
IMAGE_SIZE = int(os.getenv("IMAGE_SIZE", "640"))
DEVICE = os.getenv("OCR_DEVICE", "cuda")
TABLE_PROMPT = (
    "<image>\nExtract all text and tables from this image. Preserve every table as "
    "valid HTML <table> markup, including headers, row and column spans where visible. "
    "Do not omit rows or cells. Return only the transcription and table markup."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load once at startup. Set OCR_LOAD_MODEL=false to start without model weights.
    if os.getenv("OCR_LOAD_MODEL", "true").lower() in {"1", "true", "yes"}:
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer

            if DEVICE == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("OCR_DEVICE=cuda but CUDA is unavailable")
            app.state.tokenizer = AutoTokenizer.from_pretrained(
                MODEL_NAME, trust_remote_code=True
            )
            app.state.model = AutoModel.from_pretrained(
                MODEL_NAME,
                trust_remote_code=True,
                use_safetensors=True,
                torch_dtype=torch.bfloat16 if DEVICE == "cuda" else torch.float32,
            ).eval().to(DEVICE)
            app.state.model.eval()
        except Exception as exc:
            app.state.model_error = str(exc)
    yield


app = FastAPI(title="DocIQ Python OCR", version="1.0.0", lifespan=lifespan)
origins = [value.strip() for value in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    loaded = hasattr(app.state, "model")
    return {
        "status": "ok" if loaded else "model_unavailable",
        "model": MODEL_NAME,
        "loaded": loaded,
        "error": getattr(app.state, "model_error", None),
    }


def _parse_tables(markup: str) -> list[dict[str, Any]]:
    """Parse table cells without flattening spans or losing the original HTML."""
    soup = BeautifulSoup(markup, "html.parser")
    result = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = []
            for cell in tr.find_all(["th", "td"], recursive=False):
                item: dict[str, Any] = {
                    "text": " ".join(cell.stripped_strings),
                    "type": cell.name,
                }
                for attr in ("rowspan", "colspan"):
                    if cell.has_attr(attr):
                        try:
                            item[attr] = int(cell[attr])
                        except (ValueError, TypeError):
                            pass
                cells.append(item)
            if cells:
                rows.append(cells)
        result.append({"rows": rows, "html": str(table)})
    return result


def _run_model(image_path: str, output_dir: str) -> str:
    model = getattr(app.state, "model", None)
    tokenizer = getattr(app.state, "tokenizer", None)
    if model is None or tokenizer is None:
        detail = getattr(app.state, "model_error", "Model has not been loaded")
        raise HTTPException(status_code=503, detail=f"OCR model unavailable: {detail}")

    # DeepSeek-OCR performs dynamic crops and emits structured HTML for tables.
    value = model.infer(
        tokenizer,
        prompt=TABLE_PROMPT,
        image_file=image_path,
        output_path=output_dir,
        base_size=BASE_SIZE,
        image_size=IMAGE_SIZE,
        crop_mode=True,
        save_results=True,
    )
    if isinstance(value, str) and value.strip():
        return value.strip()
    # Some versions write the transcription to disk and return None.
    candidates = sorted(Path(output_dir).rglob("*.md")) + sorted(Path(output_dir).rglob("*.html")) + sorted(Path(output_dir).rglob("*.txt"))
    if candidates:
        return candidates[0].read_text(encoding="utf-8", errors="replace").strip()
    raise RuntimeError("The OCR model returned no text. Check model version and inference output.")


@app.post("/api/ocr/table")
async def extract_table(image: UploadFile = File(...)) -> dict[str, Any]:
    allowed = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp", "image/gif"}
    if image.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, WEBP, TIFF, or BMP image")
    data = await image.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded image is empty")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Image exceeds {MAX_UPLOAD_MB} MB")

    with tempfile.TemporaryDirectory(prefix="dociq-ocr-") as workdir:
        path = Path(workdir) / "upload"
        path.write_bytes(data)
        try:
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                width, height = img.size
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(status_code=400, detail="The uploaded file is not a valid image") from exc
        try:
            raw = await asyncio.to_thread(_run_model, str(path), workdir)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"OCR inference failed: {exc}") from exc

    tables = _parse_tables(raw)
    return {
        "success": True,
        "text": raw,
        "tables": tables,
        "table_count": len(tables),
        "image_dims": {"width": width, "height": height},
        "metadata": {"model": MODEL_NAME, "base_size": BASE_SIZE, "image_size": IMAGE_SIZE},
    }
