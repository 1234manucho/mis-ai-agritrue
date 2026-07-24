"""Flask routes for the AgriTrue image and document analyzer."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from agri_analyzer import (
    AnalyzerError,
    analyze_agricultural_image,
    analyze_document_file,
    normalize_image,
)
from extensions import db
from models import DiagnosticResult


analyzer_bp = Blueprint("analyzer", __name__)

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "heif"}
DOCUMENT_EXTENSIONS = IMAGE_EXTENSIONS | {"pdf", "docx", "csv", "txt"}
MAX_UPLOAD_BYTES = 18 * 1024 * 1024


def _upload_folder() -> Path:
    configured = current_app.config.get("UPLOAD_FOLDER", "uploads")
    folder = Path(configured)
    if not folder.is_absolute():
        folder = Path(current_app.root_path) / folder
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _extension(filename: str) -> str:
    safe = secure_filename(filename or "")
    if "." not in safe:
        return ""
    return safe.rsplit(".", 1)[1].lower()


def _json_error(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status


def _require_upload(allowed_extensions: set[str]):
    uploaded = request.files.get("file")
    if uploaded is None:
        raise AnalyzerError("No file was received.")
    if not uploaded.filename:
        raise AnalyzerError("Select a file before starting the analysis.")

    extension = _extension(uploaded.filename)
    if extension not in allowed_extensions:
        readable = ", ".join(sorted(ext.upper() for ext in allowed_extensions))
        raise AnalyzerError(f"Unsupported file type. Allowed formats: {readable}.")

    return uploaded, extension


def _temporary_path(extension: str) -> Path:
    return _upload_folder() / f"tmp-{uuid.uuid4().hex}.{extension}"


def _save_diagnostic(result, image_url: str) -> bool:
    if result.category not in {"crop", "animal"}:
        return False

    diagnosis_type = "plant" if result.category == "crop" else "animal"
    record = DiagnosticResult(
        user_id=current_user.id,
        image_url=image_url,
        diagnosis_name=result.condition_name or result.subject or "Unclear finding",
        diagnosis_type=diagnosis_type,
        cause="; ".join(result.likely_causes)[:2000] or "Not established from image",
        treatment="; ".join(result.immediate_actions)[:2000] or "Professional review advised",
        confidence_score=result.confidence_percent,
        created_at=datetime.utcnow(),
    )

    try:
        db.session.add(record)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Could not save diagnostic history")
        return False


@analyzer_bp.app_errorhandler(RequestEntityTooLarge)
def handle_large_upload(_error):
    return _json_error("The file is too large. Upload a file smaller than 18 MB.", 413)


@analyzer_bp.route("/ml-analyzer", methods=["GET"])
@login_required
def ml_analyzer():
    return render_template("ml_analyzer.html")


@analyzer_bp.route("/api/analyze_image", methods=["POST"])
@login_required
def analyze_image():
    raw_path: Path | None = None
    normalized_path: Path | None = None

    try:
        uploaded, extension = _require_upload(IMAGE_EXTENSIONS)
        raw_path = _temporary_path(extension)
        uploaded.save(raw_path)
        if raw_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise AnalyzerError("The file is too large. Upload a file smaller than 18 MB.")

        normalized_name = f"diagnostic-{current_user.id}-{uuid.uuid4().hex}.jpg"
        normalized_path = _upload_folder() / normalized_name
        normalize_image(raw_path, normalized_path)

        result = analyze_agricultural_image(normalized_path)
        image_url = url_for("analyzer.uploaded_diagnostic", filename=normalized_name)
        saved = _save_diagnostic(result, image_url)

        if result.category not in {"crop", "animal"}:
            normalized_path.unlink(missing_ok=True)
            image_url = None

        return jsonify(
            {
                "success": True,
                "analysis": result.model_dump(),
                "image_url": image_url,
                "saved_to_history": saved,
            }
        )
    except AnalyzerError as exc:
        if normalized_path:
            normalized_path.unlink(missing_ok=True)
        return _json_error(str(exc), 422)
    except Exception:
        if normalized_path:
            normalized_path.unlink(missing_ok=True)
        current_app.logger.exception("Image analysis failed")
        return _json_error("Image analysis failed unexpectedly. Please try again.", 500)
    finally:
        if raw_path:
            raw_path.unlink(missing_ok=True)


@analyzer_bp.route("/api/analyze_document", methods=["POST"])
@login_required
def analyze_document():
    temp_path: Path | None = None

    try:
        uploaded, extension = _require_upload(DOCUMENT_EXTENSIONS)
        temp_path = _temporary_path(extension)
        uploaded.save(temp_path)
        if temp_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise AnalyzerError("The file is too large. Upload a file smaller than 18 MB.")

        result = analyze_document_file(temp_path, extension)
        return jsonify(
            {
                "success": True,
                "analysis": result.model_dump(),
                "file": {
                    "name": secure_filename(uploaded.filename),
                    "type": extension,
                },
            }
        )
    except AnalyzerError as exc:
        return _json_error(str(exc), 422)
    except Exception:
        current_app.logger.exception("Document analysis failed")
        return _json_error("Document analysis failed unexpectedly. Please try again.", 500)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


@analyzer_bp.route("/api/diagnostics", methods=["GET"])
@login_required
def get_diagnostics():
    try:
        requested_limit = int(request.args.get("limit", 12))
    except ValueError:
        requested_limit = 12
    limit = max(1, min(requested_limit, 50))

    diagnostics = (
        DiagnosticResult.query.filter_by(user_id=current_user.id)
        .order_by(DiagnosticResult.created_at.desc())
        .limit(limit)
        .all()
    )

    return jsonify(
        {
            "success": True,
            "diagnostics": [
                {
                    "id": item.id,
                    "diagnosis_name": item.diagnosis_name,
                    "diagnosis_type": item.diagnosis_type,
                    "image_url": item.image_url,
                    "confidence": item.confidence_score,
                    "cause": item.cause,
                    "treatment": item.treatment,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in diagnostics
            ],
        }
    )


@analyzer_bp.route("/uploads/<path:filename>", methods=["GET"])
@login_required
def uploaded_diagnostic(filename: str):
    return send_from_directory(_upload_folder(), filename)