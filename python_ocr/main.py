"""FastAPI service for image OCR with PP-OCRv6 or DeepSeek-OCR."""

from __future__ import annotations

import asyncio
import json
import logging
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
logger = logging.getLogger("dociq.ocr")

MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-OCR")
OCR_ENGINE = os.getenv("OCR_ENGINE", "ppocrv6").strip().lower()
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "en").strip()
PADDLE_DEVICE = os.getenv("PADDLEOCR_DEVICE", "cpu").strip()
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
BASE_SIZE = int(os.getenv("BASE_SIZE", "1024"))
IMAGE_SIZE = int(os.getenv("IMAGE_SIZE", "640"))
DEVICE = os.getenv("OCR_DEVICE", "cpu")
TABLE_PROMPT = (
    "<image>\nExtract all text and tables from this image. Preserve every table as "
    "valid HTML <table> markup, including headers, row and column spans where visible. "
    "Do not omit rows or cells. Return only the transcription and table markup."
)
def _load_configured_model() -> tuple[Any, Any | None]:
    if OCR_ENGINE == "ppocrv6":
        if PADDLE_DEVICE.lower().startswith("cpu"):
            # PaddleX 3.7 selects oneDNN by default on CPU; disable that path for
            # PaddlePaddle 3.3.1's PP-OCRv6 PIR inference compatibility.
            os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "false")
        from paddleocr import PaddleOCR

        return (
            PaddleOCR(
                lang=OCR_LANGUAGE,
                ocr_version="PP-OCRv6",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                device=PADDLE_DEVICE,
            ),
            None,
        )

    if OCR_ENGINE == "deepseek":
        import torch
        from transformers import AutoModel, AutoTokenizer

        if DEVICE == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("OCR_DEVICE=cuda but CUDA is unavailable")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
        model = AutoModel.from_pretrained(
            MODEL_NAME,
            trust_remote_code=True,
            use_safetensors=True,
            torch_dtype=torch.bfloat16 if DEVICE == "cuda" else torch.float32,
        ).eval().to(DEVICE)
        model.eval()
        return model, tokenizer

    raise RuntimeError("OCR_ENGINE must be ppocrv6 or deepseek")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load once at startup. Set OCR_LOAD_MODEL=false to start without model weights.
    if os.getenv("OCR_LOAD_MODEL", "true").lower() in {"1", "true", "yes"}:
        try:
            app.state.model, tokenizer = _load_configured_model()
            if tokenizer is not None:
                app.state.tokenizer = tokenizer
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
        "engine": OCR_ENGINE,
        "model": "PP-OCRv6" if OCR_ENGINE == "ppocrv6" else MODEL_NAME,
        "language": OCR_LANGUAGE if OCR_ENGINE == "ppocrv6" else None,
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
    if model is None:
        detail = getattr(app.state, "model_error", "Model has not been loaded")
        raise HTTPException(status_code=503, detail=f"OCR model unavailable: {detail}")

    if OCR_ENGINE == "ppocrv6":
        predictions = model.predict(image_path)
        if isinstance(predictions, dict):
            predictions = [predictions]
        elif predictions is None:
            predictions = []
        else:
            predictions = list(predictions)
        logger.info(
            "PP-OCRv6 predict returned %d prediction(s); result types: %s",
            len(predictions),
            [type(prediction).__name__ for prediction in predictions],
        )
        boxes_by_row: list[tuple[float, float, float, str]] = []
        for prediction_index, prediction in enumerate(predictions):
            payload = getattr(prediction, "json", None)
            if callable(payload):
                payload = payload()
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    logger.warning(
                        "PP-OCRv6 prediction %d returned non-JSON text payload",
                        prediction_index,
                    )
                    continue
            if not isinstance(payload, dict) and isinstance(prediction, dict):
                payload = prediction
            if not isinstance(payload, dict):
                logger.warning(
                    "PP-OCRv6 prediction %d has unsupported payload type %s",
                    prediction_index,
                    type(payload).__name__,
                )
                continue
            result = payload.get("res", payload)
            if not isinstance(result, dict):
                logger.warning(
                    "PP-OCRv6 prediction %d has non-dict result type %s; payload keys: %s",
                    prediction_index,
                    type(result).__name__,
                    sorted(payload.keys()),
                )
                continue
            raw_texts = result.get("rec_texts")
            if raw_texts is None or (hasattr(raw_texts, "__len__") and len(raw_texts) == 0):
                raw_texts = result.get("texts")
            if raw_texts is None:
                raw_texts = result.get("text")
            if raw_texts is None:
                raw_texts = []
            if hasattr(raw_texts, "tolist"):
                raw_texts = raw_texts.tolist()
            if isinstance(raw_texts, str):
                raw_texts = [raw_texts]
            elif not isinstance(raw_texts, (list, tuple)):
                raw_texts = []

            logger.info(
                "PP-OCRv6 prediction %d result keys: %s; text fields found: %s; text item count: %d",
                prediction_index,
                sorted(result.keys()),
                [key for key in ("rec_texts", "texts", "text") if key in result],
                len(raw_texts),
            )
            texts = raw_texts
            boxes = result.get("rec_boxes")
            if boxes is None:
                boxes = result.get("rec_polys")
            if boxes is None:
                boxes = []
            elif hasattr(boxes, "tolist"):
                boxes = boxes.tolist()
            for index, raw_text in enumerate(texts):
                text = str(raw_text).strip()
                if not text:
                    continue
                try:
                    box = boxes[index]
                    # PP-OCR may return [x1, y1, x2, y2] rectangles or polygons.
                    if len(box) == 4 and not hasattr(box[0], "__len__"):
                        left, top, right, bottom = (float(value) for value in box)
                    else:
                        points = [list(point) for point in box]
                        left = min(float(point[0]) for point in points)
                        top = min(float(point[1]) for point in points)
                        right = max(float(point[0]) for point in points)
                        bottom = max(float(point[1]) for point in points)
                    height = max(1.0, bottom - top)
                    boxes_by_row.append((top + height / 2, left, height, text))
                except (TypeError, ValueError, IndexError):
                    boxes_by_row.append((float(index), 0.0, 1.0, text))

        boxes_by_row.sort(key=lambda item: (item[0], item[1]))
        rows: list[list[tuple[float, float, float, str]]] = []
        for item in boxes_by_row:
            if rows:
                center = sum(entry[0] for entry in rows[-1]) / len(rows[-1])
                row_height = sum(entry[2] for entry in rows[-1]) / len(rows[-1])
                if abs(item[0] - center) <= max(8.0, min(item[2], row_height) * 0.6):
                    rows[-1].append(item)
                    continue
            rows.append([item])

        text = "\n".join(
            "  ".join(item[3] for item in sorted(row, key=lambda entry: entry[1]))
            for row in rows
        )
        if text.strip():
            return text.strip()
        logger.warning(
            "PP-OCRv6 returned no text after parsing; prediction count: %d",
            len(predictions),
        )
        raise RuntimeError("PP-OCRv6 returned no recognized English text.")

    tokenizer = getattr(app.state, "tokenizer", None)
    if OCR_ENGINE != "deepseek" or tokenizer is None:
        raise HTTPException(status_code=503, detail="The configured OCR engine is unavailable")

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
    allowed = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/tiff": ".tiff",
        "image/bmp": ".bmp",
        "image/gif": ".gif",
    }
    if image.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, WEBP, TIFF, or BMP image")
    data = await image.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded image is empty")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Image exceeds {MAX_UPLOAD_MB} MB")

    with tempfile.TemporaryDirectory(prefix="dociq-ocr-") as workdir:
        suffix = Path(image.filename or "").suffix.lower()
        supported_suffixes = {
            "image/jpeg": {".jpg", ".jpeg"},
            "image/png": {".png"},
            "image/webp": {".webp"},
            "image/tiff": {".tif", ".tiff"},
            "image/bmp": {".bmp"},
            "image/gif": {".gif"},
        }
        if suffix not in supported_suffixes[image.content_type]:
            suffix = allowed[image.content_type]
        path = Path(workdir) / f"upload{suffix}"
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
        "metadata": {
            "engine": OCR_ENGINE,
            "model": "PP-OCRv6" if OCR_ENGINE == "ppocrv6" else MODEL_NAME,
            "language": OCR_LANGUAGE if OCR_ENGINE == "ppocrv6" else None,
            **({} if OCR_ENGINE == "ppocrv6" else {"base_size": BASE_SIZE, "image_size": IMAGE_SIZE}),
        },
    }
