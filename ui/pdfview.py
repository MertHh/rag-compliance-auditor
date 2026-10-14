import hashlib
import json

from streamlit_pdf_viewer import pdf_viewer


def viewer_key(key: str, annotations: list[dict]) -> str:
    """The viewer redraws only when the PDF bytes change, so new boxes need a new key."""
    digest = hashlib.sha1(json.dumps(annotations, sort_keys=True).encode()).hexdigest()[:10]
    return f"{key}_{digest}"


def show_pdf(data: bytes, annotations: list[dict], key: str) -> None:
    """Shows the PDF with boxes drawn over the cited text and scrolls to the first box."""
    pdf_viewer(
        data,
        width="100%",
        height=820,
        annotations=annotations,
        annotation_outline_size=2,
        scroll_to_annotation=1 if annotations else None,
        key=viewer_key(key, annotations),
    )
